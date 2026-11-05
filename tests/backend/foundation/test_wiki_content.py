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
