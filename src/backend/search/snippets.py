import html
import re
from typing import List, Optional
from src.backend.search.analyzer import default_analyzer, TextAnalyzer


def generate_snippet(
    text: str,
    query_terms: List[str],
    max_length: int = 180,
    summary: Optional[str] = None,
) -> str:
    """
    Generates a secure, HTML-escaped text snippet with <em>...</em> highlighted query terms.
    - Raw input text is strictly HTML-escaped before highlighting to prevent XSS.
    - Locates the most relevant text window around query term occurrences.
    - Falls back gracefully to the document summary or text prefix if terms are not present.
    """
    source_text = (text or "").strip()
    if not source_text and summary:
        source_text = summary.strip()

    if not source_text:
        return ""

    # Clean multi-spaces and newlines into single spaces for display
    normalized_source = re.sub(r"\s+", " ", source_text)

    # Filter out empty or whitespace query terms
    clean_terms = [t.strip() for t in query_terms if t and t.strip()]

    if not clean_terms:
        # No query terms: return prefix of escaped text
        escaped = html.escape(normalized_source)
        if len(escaped) > max_length:
            return escaped[:max_length].rstrip() + "..."
        return escaped

    # Search for term occurrences (case-insensitive, whole word boundary preferred)
    escaped_patterns = [re.escape(t) for t in clean_terms]
    pattern_regex = re.compile(r"\b(" + "|".join(escaped_patterns) + r")\b", re.IGNORECASE)

    matches = list(pattern_regex.finditer(normalized_source))

    if not matches:
        # Try substring match if word boundary didn't match (e.g. compound tokens or numbers)
        sub_regex = re.compile(r"(" + "|".join(escaped_patterns) + r")", re.IGNORECASE)
        matches = list(sub_regex.finditer(normalized_source))

    if not matches:
        # Fall back to summary or prefix
        fallback_text = summary.strip() if summary else normalized_source
        fallback_norm = re.sub(r"\s+", " ", fallback_text)
        escaped = html.escape(fallback_norm)
        if len(escaped) > max_length:
            return escaped[:max_length].rstrip() + "..."
        return escaped

    # Prefer a passage covering all query terms over an early incidental mention.
    def window_quality(match):
        start = max(0, match.start() - 40)
        window = normalized_source[start:start + max_length]
        return len({m.group(0).casefold() for m in pattern_regex.finditer(window)})

    first_match = max(matches, key=window_quality)
    match_start = first_match.start()
    match_end = first_match.end()

    # Determine window boundaries
    lead_chars = 40
    start_pos = max(0, match_start - lead_chars)
    end_pos = min(len(normalized_source), start_pos + max_length)

    # Adjust start_pos to a word boundary if possible
    if start_pos > 0:
        prev_space = normalized_source.find(" ", start_pos)
        if prev_space != -1 and prev_space < match_start:
            start_pos = prev_space + 1

    # Adjust end_pos to a word boundary if possible
    if end_pos < len(normalized_source):
        next_space = normalized_source.rfind(" ", start_pos, end_pos)
        if next_space != -1 and next_space > match_end:
            end_pos = next_space

    window_text = normalized_source[start_pos:end_pos]

    # HTML-escape the window text BEFORE applying <em> highlights
    escaped_window = html.escape(window_text)

    # Now highlight query terms within the escaped text
    escaped_terms = [re.escape(html.escape(t)) for t in clean_terms]
    highlight_regex = re.compile(r"\b(" + "|".join(escaped_terms) + r")\b", re.IGNORECASE)

    def replace_highlight(m):
        return f"<em>{m.group(0)}</em>"

    highlighted = highlight_regex.sub(replace_highlight, escaped_window)

    # If word boundary didn't catch all, apply non-boundary highlight
    if not highlight_regex.search(escaped_window):
        sub_highlight = re.compile(r"(" + "|".join(escaped_terms) + r")", re.IGNORECASE)
        highlighted = sub_highlight.sub(replace_highlight, escaped_window)

    prefix = "..." if start_pos > 0 else ""
    suffix = "..." if end_pos < len(normalized_source) else ""

    return f"{prefix}{highlighted.strip()}{suffix}"
