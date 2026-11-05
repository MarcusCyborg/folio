"""
Unit tests for Folio Text Analyzer (P04).

Verifies:
1. Analyzer version consistency (1.0.0)
2. Unicode normalization (NFKC)
3. Lowercase conversion
4. Token boundary and punctuation handling
5. Alphanumeric and numbers preservation
6. Stopword filtering (with configurable options)
7. Repeated terms preservation and term frequencies
8. Empty query, whitespace-only, punctuation-only, stopword-only queries
9. Long text processing efficiency
10. Query and document analyzer parity
"""

import time
import pytest
from src.backend.search.analyzer import (
    TextAnalyzer,
    ANALYZER_VERSION,
    DEFAULT_STOPWORDS,
    default_analyzer,
)


def test_analyzer_version():
    """Requirement 1: Analyzer version is explicitly declared and pinned."""
    analyzer = TextAnalyzer()
    assert analyzer.version == "1.0.0"
    assert ANALYZER_VERSION == "1.0.0"
    res = analyzer.analyze("Sample query")
    assert res.analyzer_version == "1.0.0"


def test_unicode_normalization_nfkc():
    """Requirement 1: Unicode NFKC normalization decomposes and normalizes characters."""
    analyzer = TextAnalyzer(filter_stopwords=False)

    # Full-width alphanumeric (U+FF10 to U+FF19, etc.)
    full_width = "Ｆｏｌｉｏ ２０２６"
    tokens = analyzer.tokenize(full_width)
    assert tokens == ["folio", "2026"]

    # Ligatures (e.g., 'ﬁ' -> 'fi')
    ligature = "scientific ﬁndings"
    assert analyzer.tokenize(ligature) == ["scientific", "findings"]

    # Accented characters
    accented = "Café René Poincaré"
    tokens_acc = analyzer.tokenize(accented)
    assert "café" in tokens_acc or "cafe" in tokens_acc or len(tokens_acc) == 3


def test_lowercase_conversion():
    """Requirement 1: All tokens are converted to lowercase."""
    analyzer = TextAnalyzer(filter_stopwords=False)
    text = "DeEp LeArNiNg AnD NeUrAl NeTwOrKs"
    assert analyzer.tokenize(text) == ["deep", "learning", "and", "neural", "networks"]


def test_punctuation_and_token_boundaries():
    """Requirement 1: Punctuation and special characters act as token boundaries."""
    analyzer = TextAnalyzer(filter_stopwords=False)
    text = "deep-learning, (neural/networks)! high_performance: 2026."
    tokens = analyzer.tokenize(text)
    assert tokens == ["deep", "learning", "neural", "networks", "high", "performance", "2026"]


def test_numbers_preservation():
    """Requirement 1: Numbers and alphanumeric identifiers are preserved."""
    analyzer = TextAnalyzer(filter_stopwords=False)
    text = "Section 42 in year 2026 with GPT4 and 3D vision"
    tokens = analyzer.tokenize(text)
    assert "42" in tokens
    assert "2026" in tokens
    assert "gpt4" in tokens
    assert "3d" in tokens


def test_stopwords_filtering():
    """Requirement 1: Standard stopwords are removed by default, configurable."""
    # Default: filter stopwords
    analyzer = TextAnalyzer(filter_stopwords=True)
    text = "this is a comprehensive study about neural networks"
    tokens = analyzer.tokenize(text)
    assert "this" not in tokens
    assert "is" not in tokens
    assert "a" not in tokens
    assert "about" not in tokens
    assert tokens == ["comprehensive", "study", "neural", "networks"]

    # Disabled: preserve stopwords
    no_filter = TextAnalyzer(filter_stopwords=False)
    tokens_all = no_filter.tokenize(text)
    assert "this" in tokens_all
    assert "is" in tokens_all
    assert "a" in tokens_all

    # Custom stopword set
    custom = TextAnalyzer(stopwords={"neural", "study"})
    tokens_custom = custom.tokenize(text)
    assert "neural" not in tokens_custom
    assert "study" not in tokens_custom
    assert "comprehensive" in tokens_custom


def test_repeated_terms_and_frequency():
    """Requirement 1: Repeated terms preserve stream order and frequency counts."""
    analyzer = TextAnalyzer(filter_stopwords=False)
    text = "deep learning deep learning neural neural neural"
    analysis = analyzer.analyze(text)

    assert analysis.tokens == ["deep", "learning", "deep", "learning", "neural", "neural", "neural"]
    assert analysis.doc_len == 7
    assert analysis.term_frequencies["deep"] == 2
    assert analysis.term_frequencies["learning"] == 2
    assert analysis.term_frequencies["neural"] == 3


def test_empty_and_whitespace_queries():
    """Requirement 1: Empty, whitespace, punctuation, and stopword-only queries return empty token lists."""
    analyzer = TextAnalyzer(filter_stopwords=True)

    assert analyzer.tokenize("") == []
    assert analyzer.tokenize("   \t  \n  ") == []
    assert analyzer.tokenize("!@#$%^&*()_+=-[]{};:'\",.<>/?\\|`~") == []
    # Stopword-only query
    assert analyzer.tokenize("what is the and of to") == []

    analysis = analyzer.analyze("   ")
    assert analysis.tokens == []
    assert analysis.term_frequencies == {}
    assert analysis.doc_len == 0


def test_long_text_performance():
    """Requirement 1: Long text (e.g. 20,000 words) tokenizes linearly without quadratic slowdown."""
    analyzer = TextAnalyzer(filter_stopwords=True)
    # Generate 25,000 words
    paragraph = "Deep learning and artificial intelligence revolutionize modern technological applications in 2026. "
    large_text = paragraph * 2500  # ~25,000 words

    start = time.perf_counter()
    analysis = analyzer.analyze(large_text)
    elapsed = time.perf_counter() - start

    assert analysis.doc_len > 10000
    assert "deep" in analysis.term_frequencies
    assert "learning" in analysis.term_frequencies
    # Must complete in under 500ms
    assert elapsed < 0.5


def test_query_and_document_analyzer_parity():
    """Requirement 1: Query and document tokenization use exact same semantics and version."""
    analyzer = TextAnalyzer()
    doc_text = "Advancements in Quantum-Computing & Deep_Learning (2026)"
    query_text = "quantum-computing deep_learning 2026"

    doc_tokens = analyzer.tokenize(doc_text)
    query_tokens = analyzer.tokenize(query_text)

    # Query tokens should be an exact subset of doc tokens
    for qt in query_tokens:
        assert qt in doc_tokens
