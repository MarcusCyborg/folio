import json
from pathlib import Path

import pytest

from src.backend.core.wiki_content import clean_wikipedia_content


WIKI_URL = "https://en.wikipedia.org/wiki/Open_letter_on_artificial_intelligence"


@pytest.mark.parametrize("marker", ["[edit]", "[edit source]"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_removes_section_controls_and_is_idempotent(marker, newline):
    content = newline.join(["## Background", "", marker, "", "Keep the article.", "", "### Purpose", "", marker])
    expected = newline.join(["## Background", "", "Keep the article.", "", "### Purpose", "", ""])
    cleaned = clean_wikipedia_content(content, WIKI_URL)
    assert cleaned == expected
    assert clean_wikipedia_content(cleaned, WIKI_URL) == cleaned


@pytest.mark.parametrize("source", [None, "", "https://example.com/wiki/Article", "https://wikipedia.org.example.com/", "https://notwikipedia.org/", "https://[broken", "file://en.wikipedia.org/article"])
def test_preserves_non_wikipedia_documents(source):
    content = "## Instructions\n\n[edit]\n\nKeep this label."
    assert clean_wikipedia_content(content, source) == content


@pytest.mark.parametrize("content", [
    "The [edit] label opens the editor.",
    "[edit]\n\nA standalone label without a heading.",
    "## Example\n\n[edit](https://example.com/edit)",
    "## Example\n\n[edit]: https://example.com/edit",
    "## Example\n\n`[edit]`",
    "## Example\n\n    [edit]\n",
    "    ## Example\n\n    [edit]\n",
    "## Example\n\nBody text.\n\n[edit]\n",
    "```markdown\n## Example\n\n[edit]\n```\n",
    "~~~~markdown\n## Example\n\n[edit]\n~~~\n[edit]\n~~~~\n",
    "## Example\n\n[citation needed]\n\n[1]\n",
])
def test_preserves_prose_links_citations_and_code(content):
    assert clean_wikipedia_content(content, WIKI_URL) == content


def test_cleanup_resumes_after_fenced_code():
    code = "```markdown\n## Example\n\n[edit]\n```\n\n"
    content = code + "## Background\n\n[edit]\n\nArticle."
    assert clean_wikipedia_content(content, WIKI_URL) == code + "## Background\n\nArticle."


def test_curated_fixtures_have_no_standalone_edit_controls():
    path = Path(__file__).resolve().parents[3] / "fixtures/folio/documents.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 103
    for record in records:
        assert clean_wikipedia_content(record["content"], record["source_url"]) == record["content"]
        assert not any(line.strip() in ("[edit]", "[edit source]") for line in record["content"].splitlines()), record["title"]


def test_spider_removes_edit_controls_before_markdown_conversion():
    pytest.importorskip("scrapy")
    pytest.importorskip("markdownify")
    from scrapy.http import HtmlResponse
    from wiki_bot.wiki_bot.spiders.wiki_spider import WikipediaSpider

    paragraph = "The article explains the purpose and background of this open letter. " * 3
    html = f'''<h1 id="firstHeading">Open letter</h1><div class="mw-parser-output">
        <h2>Background<span class="mw-editsection">[<a href="/w/index.php?action=edit">edit</a>]</span></h2>
        <p>{paragraph}</p>
        <div class="mw-heading mw-heading2"><h2>Purpose</h2>
        <span class="mw-editsection">[<a href="/w/index.php?action=edit">edit source</a>]</span></div>
        <p>Keep the word edit in prose.</p></div>'''
    response = HtmlResponse(url=WIKI_URL, body=html.encode(), encoding="utf-8")
    records = [item for item in WikipediaSpider().parse(response) if isinstance(item, dict)]
    assert len(records) == 1
    assert "[edit" not in records[0]["text"]
    assert "## Background" in records[0]["text"]
    assert "## Purpose" in records[0]["text"]
    assert paragraph.strip() in records[0]["text"]
    assert "Keep the word edit in prose." in records[0]["text"]


def test_r11_math_normalization_nested_braces_code_preservation_and_xss_safety():
    """
    R11 / F08:
    1. Nested and multiline {\\displaystyle ...} / {\\textstyle ...} normalize cleanly
       without corrupting subscripts/underscores during Markdown parsing.
    2. Fenced code blocks and inline code spans preserve literal LaTeX syntax.
    3. Raw HTML / XSS payloads inside math delimiters are neutralized by sanitization.
    """
    from src.backend.core.sanitizer import render_and_sanitize_markdown

    src = (
        "== Scaled Dot-Product Attention ==\n\n"
        "{\\displaystyle {\\text{Attention}}(Q,K,V)={\\text{softmax}}\\left({\\frac {QK^{T}}{\\sqrt {d_{k}}}}\\right)V}\n\n"
        "Inline term {\\textstyle x_{1} + y_{2}} and \\(a_{i} + b_{j}\\).\n\n"
        "Inline code `{\\displaystyle literal}` and fenced block:\n\n"
        "```latex\n"
        "{\\displaystyle fenced_literal}\n"
        "```\n\n"
        "Malicious math: $$<img src=x onerror=alert(1)> x_{1}$$\n"
    )
    rendered = render_and_sanitize_markdown(src)

    assert "<h2>Scaled Dot-Product Attention</h2>" in rendered
    assert '<div class="math-display">$$' in rendered
    assert "d_{k}" in rendered
    assert "<em>" not in rendered  # underscores inside math must NOT become <em>
    assert '<span class="math-inline">\\(x_{1} + y_{2}\\)</span>' in rendered
    assert '<span class="math-inline">\\(a_{i} + b_{j}\\)</span>' in rendered
    assert "<code>{\\displaystyle literal}</code>" in rendered
    assert "{\\displaystyle fenced_literal}" in rendered
    assert "<img" not in rendered
    assert "&lt;img" in rendered
