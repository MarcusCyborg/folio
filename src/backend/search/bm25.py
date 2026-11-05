r"""
Okapi BM25 Scoring and Title Boost Implementation for Folio.

Mathematical Formulation:

1. Standard Okapi BM25 (Robertson & Spärck Jones):
   Given a query Q = (q_1, q_2, ..., q_m) and a document d:

                 m                                  tf(q_i, d) * (k_1 + 1)
       BM25(d, Q) = Sum  IDF(q_i) * ------------------------------------------------------
                i=1              tf(q_i, d) + k_1 * (1 - b + b * (|d| / avgdl))

   Where:
   - tf(q_i, d): Term frequency of term q_i in document d
   - |d|: Length of document d (in analyzed tokens)
   - avgdl: Average document length across the entire indexed corpus (total_tokens / N)
   - k_1: Term frequency saturation hyperparameter (default: 1.5, configurable)
   - b: Document length normalization hyperparameter (default: 0.75, configurable)

2. Inverse Document Frequency (IDF) - Non-Negative Lucene / Okapi Variant:
   To prevent negative IDF scores when terms appear in more than half the corpus (df > N/2),
   Folio uses the standard non-negative formulation:

                      /         N - df(q_i) + 0.5 \
       IDF(q_i) = ln | 1 + ----------------------- |
                      \          df(q_i) + 0.5    /

   Where:
   - N: Total number of published documents in the corpus (total_docs)
   - df(q_i): Number of documents containing term q_i (document frequency)
   - If df(q_i) == 0 (unknown term) or N == 0: IDF = 0.0

3. Optional Title Boost (Separated Multiplier):
   IMPORTANT: This is Title Boosted Okapi BM25, NOT BM25F.
   BM25F requires accumulating weighted term frequencies across fields before non-linear
   saturation. Here, Title Boost is a separate, post-scoring precision multiplier:

                         | Q_terms ∩ Title_terms |
       coverage(Q, T) = ---------------------------
                                | Q_terms |

       title_boost(d, Q) = 1.0 + (title_weight * coverage(Q, T))

       FinalScore(d, Q) = BM25(d, Q) * title_boost(d, Q)

   Where:
   - title_weight: Boost sensitivity parameter (default: 0.0, neutral/disabled)
   - When disabled or title_weight == 0.0: title_boost = 1.0, FinalScore == BM25.
"""

import math
from dataclasses import dataclass
from typing import List, Dict, Set, Optional, Tuple

from src.backend.search.analyzer import TextAnalyzer, default_analyzer
from src.backend.search.index import InvertedIndex, DocumentMetadata, CorpusStats


@dataclass(frozen=True)
class TermScoreBreakdown:
    """Detailed score decomposition for a single query term in a document."""
    term: str
    tf: int
    df: int
    idf: float
    tf_norm: float
    score: float


@dataclass(frozen=True)
class DocumentScore:
    """Complete scoring breakdown for a document candidate."""
    doc_id: str
    raw_bm25: float
    title_boost: float
    final_score: float
    term_breakdowns: List[TermScoreBreakdown]


class BM25Scorer:
    """
    Okapi BM25 Scorer with configurable k1, b, and optional separated title boost.
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        analyzer: Optional[TextAnalyzer] = None,
    ):
        if k1 < 0:
            raise ValueError(f"k1 must be non-negative, got {k1}")
        if not (0.0 <= b <= 1.0):
            raise ValueError(f"b must be between 0.0 and 1.0, got {b}")

        self.k1 = k1
        self.b = b
        self.analyzer = analyzer or default_analyzer

    def compute_idf(self, df: int, total_docs: int) -> float:
        """
        Computes non-negative Okapi BM25 IDF:
        IDF = ln(1 + (N - df + 0.5) / (df + 0.5))
        Guaranteed non-negative for any 0 <= df <= N.
        Returns 0.0 if df == 0 or total_docs == 0.
        """
        if total_docs <= 0 or df <= 0:
            return 0.0
        if df > total_docs:
            df = total_docs

        num = total_docs - df + 0.5
        denom = df + 0.5
        return math.log(1.0 + (num / denom))

    def compute_title_boost(
        self,
        query_terms: List[str],
        title: str,
        title_weight: float = 0.0,
    ) -> float:
        """
        Computes title boost coverage multiplier:
        coverage = |Q_terms ∩ Title_terms| / |Q_terms|
        title_boost = 1.0 + title_weight * coverage
        """
        if title_weight <= 0.0 or not query_terms or not title:
            return 1.0

        title_tokens = set(self.analyzer.tokenize(title))
        if not title_tokens:
            return 1.0

        q_terms_set = set(query_terms)
        intersection_count = len(q_terms_set & title_tokens)
        coverage = intersection_count / len(q_terms_set)
        return 1.0 + (title_weight * coverage)

    def score_candidate(
        self,
        doc_id: str,
        term_freqs: Dict[str, int],
        index: InvertedIndex,
        query_terms: List[str],
        title_weight: float = 0.0,
    ) -> DocumentScore:
        """
        Scores a single document candidate against query terms using Okapi BM25.
        """
        doc_meta = index.documents.get(doc_id)
        if not doc_meta:
            return DocumentScore(
                doc_id=doc_id,
                raw_bm25=0.0,
                title_boost=1.0,
                final_score=0.0,
                term_breakdowns=[],
            )

        total_docs = index.total_docs
        avgdl = index.avg_doc_len
        doc_len = doc_meta.doc_len

        # Edge case: empty corpus or zero avgdl
        if total_docs == 0 or avgdl <= 0:
            return DocumentScore(
                doc_id=doc_id,
                raw_bm25=0.0,
                title_boost=1.0,
                final_score=0.0,
                term_breakdowns=[],
            )

        raw_bm25 = 0.0
        breakdowns: List[TermScoreBreakdown] = []

        # Length normalization factor K = k1 * (1 - b + b * (|d| / avgdl))
        k_factor = self.k1 * (1.0 - self.b + self.b * (doc_len / avgdl))

        for term in query_terms:
            tf = term_freqs.get(term, 0)
            if tf <= 0:
                continue

            df = index.df.get(term, 0)
            idf = self.compute_idf(df, total_docs)
            if idf <= 0.0:
                continue

            # tf_norm = (tf * (k1 + 1)) / (tf + K)
            tf_norm = (tf * (self.k1 + 1.0)) / (tf + k_factor)
            term_score = idf * tf_norm
            raw_bm25 += term_score

            breakdowns.append(
                TermScoreBreakdown(
                    term=term,
                    tf=tf,
                    df=df,
                    idf=idf,
                    tf_norm=tf_norm,
                    score=term_score,
                )
            )

        # Title boost
        title_boost = self.compute_title_boost(query_terms, doc_meta.title, title_weight)
        final_score = raw_bm25 * title_boost

        return DocumentScore(
            doc_id=doc_id,
            raw_bm25=raw_bm25,
            title_boost=title_boost,
            final_score=final_score,
            term_breakdowns=breakdowns,
        )
