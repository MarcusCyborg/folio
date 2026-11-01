"""
Folio Information Retrieval and Search Package.

Exports core IR components for tokenization, indexing, BM25 scoring, and candidate retrieval.
"""

from src.backend.search.analyzer import (
    ANALYZER_VERSION,
    AnalysisResult,
    TextAnalyzer,
    default_analyzer,
)
from src.backend.search.index import (
    InvertedIndex,
    DocumentMetadata,
    CorpusStats,
    GenerationMismatchError,
)
from src.backend.search.bm25 import (
    BM25Scorer,
    DocumentScore,
    TermScoreBreakdown,
)
from src.backend.search.tfidf import (
    TfIdfScorer,
)
from src.backend.search.builder import (
    IndexBuilder,
)
from src.backend.search.engine import (
    SearchEngine,
    SearchQuery,
    SearchResponse,
    CandidateHit,
)

__all__ = [
    "ANALYZER_VERSION",
    "AnalysisResult",
    "TextAnalyzer",
    "default_analyzer",
    "InvertedIndex",
    "DocumentMetadata",
    "CorpusStats",
    "GenerationMismatchError",
    "BM25Scorer",
    "DocumentScore",
    "TermScoreBreakdown",
    "TfIdfScorer",
    "IndexBuilder",
    "SearchEngine",
    "SearchQuery",
    "SearchResponse",
    "CandidateHit",
]
