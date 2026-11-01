"""
Folio Text Analyzer for Information Retrieval.

Implements versioned text analysis for both indexing and query evaluation:
- Unicode normalization (NFKC)
- Lowercasing
- Token boundary and punctuation stripping (treating punctuation, whitespace, and underscores as boundaries)
- Alphanumeric and numeric token preservation (e.g., '2026', 'gpt4')
- Configurable stopword removal (self-contained, no external NLTK dependencies)
- Preservation of repeated terms and term frequencies
- Graceful handling of empty queries and whitespace-only text
- Efficient linear-time processing of long texts
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import List, Set, Dict, Optional
from collections import Counter

ANALYZER_VERSION: str = "1.0.0"

# Standard English stopword list (self-contained, 127 words, zero external ML/NLTK dependency)
DEFAULT_STOPWORDS: frozenset[str] = frozenset({
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but",
    "by", "can", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from",
    "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him",
    "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just",
    "me", "more", "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on",
    "once", "only", "or", "other", "our", "ours", "ourselves", "out", "over", "own", "same",
    "she", "should", "so", "some", "such", "than", "that", "the", "their", "theirs", "them",
    "themselves", "then", "there", "these", "they", "this", "those", "through", "to", "too",
    "under", "until", "up", "very", "was", "we", "were", "what", "when", "where", "which",
    "while", "who", "whom", "why", "will", "with", "you", "your", "yours", "yourself", "yourselves"
})

# Matches sequences of Unicode word characters excluding underscore
_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class AnalysisResult:
    """Encapsulates the output of analyzing a text snippet or document."""
    tokens: List[str]
    term_frequencies: Dict[str, int]
    doc_len: int
    analyzer_version: str = ANALYZER_VERSION


class TextAnalyzer:
    """
    Standard text analyzer for the Folio Information Retrieval pipeline.
    Ensures identical tokenization semantics for both documents and search queries.
    """

    def __init__(
        self,
        stopwords: Optional[Set[str]] = None,
        filter_stopwords: bool = True,
        version: str = ANALYZER_VERSION,
    ):
        self.version = version
        self.filter_stopwords = filter_stopwords
        self.stopwords = frozenset(stopwords) if stopwords is not None else DEFAULT_STOPWORDS

    def tokenize(self, text: Optional[str]) -> List[str]:
        """
        Tokenizes an input string into a list of normalized tokens:
        1. Handle None or empty text -> []
        2. Unicode normalization (NFKC)
        3. Lowercase conversion
        4. Token extraction on word boundaries, treating punctuation as separators
        5. Stopword filtering (if enabled)
        Preserves token stream order and repeated terms.
        """
        if not text:
            return []

        # 1. Unicode normalization (NFKC)
        normalized = unicodedata.normalize("NFKC", text)

        # 2. Lowercasing
        lowered = normalized.lower()

        # 3. Token boundary extraction
        raw_tokens = _TOKEN_PATTERN.findall(lowered)

        # 4. Stopwords filtering
        if self.filter_stopwords and self.stopwords:
            return [tok for tok in raw_tokens if tok not in self.stopwords]

        return raw_tokens

    def analyze(self, text: Optional[str]) -> AnalysisResult:
        """
        Analyzes an input string and produces token list, term frequency Counter,
        and document length.
        """
        tokens = self.tokenize(text)
        term_freqs = dict(Counter(tokens))
        doc_len = len(tokens)
        return AnalysisResult(
            tokens=tokens,
            term_frequencies=term_freqs,
            doc_len=doc_len,
            analyzer_version=self.version,
        )


# Global default analyzer instance
default_analyzer = TextAnalyzer()
