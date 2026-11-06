import re
import markdown
import bleach

ALLOWED_TAGS = [
    'a', 'abbr', 'acronym', 'b', 'blockquote', 'code', 'em', 'i', 'li', 'ol',
    'strong', 'ul', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'pre', 'hr',
    'table', 'thead', 'tbody', 'tr', 'th', 'td', 'img', 'span', 'div', 'br', 's', 'sub', 'sup'
]

def filter_attributes(tag, name, value):
    if tag == 'a':
        if name in ['target', 'rel', 'title']:
            return True
        if name == 'href':
            if '"' in value or '&quot;' in value or "'" in value:
                return False
            if 'on' in value.lower() and ('pointer' in value.lower() or 'click' in value.lower() or 'mouse' in value.lower() or '=' in value):
                return False
            return True
    elif tag == 'img':
        if name in ['alt', 'title', 'loading', 'width', 'height']:
            return True
        if name == 'src':
            return '"' not in value and '&quot;' not in value
    elif tag in ['th', 'td'] and name == 'align':
        return True
    elif tag == 'code' and name == 'class':
        return True
    elif tag in ['div', 'span'] and name == 'class':
        return value in ['math-display', 'math-inline', 'katex-display']
    return False

ALLOWED_PROTOCOLS = ['http', 'https', 'mailto']

def normalize_markdown_syntax(content: str) -> str:
    r"""
    Normalizes MediaWiki-style headings and math blocks into standard Markdown/HTML:
    - == Heading == -> ## Heading outside fenced code blocks (F08)
    - {\displaystyle ...} -> <div class="math-display">$$...$$</div> (F08)
    """
    if not content:
        return ""

    result = []
    fence = None
    for line in content.splitlines(keepends=True):
        raw_line = line.rstrip("\r\n")
        # Fenced code block tracking
        if fence:
            result.append(line)
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + r"{" + str(len(fence)) + r",}[ \t]*", raw_line):
                fence = None
            continue

        fence_match = re.match(r" {0,3}(`{3,}|~{3,})", line)
        if fence_match:
            fence = fence_match.group(1)
            result.append(line)
            continue

        # F08: Normalize MediaWiki headings: == Heading == -> ## Heading
        heading_match = re.match(r"^(={2,6})\s*(.*?)\s*\1$", raw_line)
        if heading_match:
            eq_len = len(heading_match.group(1))
            heading_text = heading_match.group(2)
            ending = "\r\n" if line.endswith("\r\n") else "\n"
            line = f"{'#' * eq_len} {heading_text}{ending}"
            raw_line = line.rstrip("\r\n")

        # F08: Normalize {\displaystyle ...} math blocks to standard math-display
        if "{\\displaystyle" in line:
            line = re.sub(
                r"\{\\displaystyle\s*([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}",
                r'<div class="math-display">$$\1$$</div>',
                line
            )

        result.append(line)

    return "".join(result)

def render_and_sanitize_markdown(raw_markdown: str) -> str:
    """Renders markdown to HTML and thoroughly sanitizes it."""
    if not raw_markdown:
        return ""
    # Normalize MediaWiki headings and math delimiters before parsing
    normalized = normalize_markdown_syntax(raw_markdown)
    # Render with standard markdown extensions
    raw_html = markdown.markdown(
        normalized,
        extensions=['fenced_code', 'tables', 'nl2br']
    )
    # Sanitize with bleach allowlist
    clean_html = bleach.clean(
        raw_html,
        tags=ALLOWED_TAGS,
        attributes=filter_attributes,
        protocols=ALLOWED_PROTOCOLS,
        strip=True
    )
    # Ensure links have rel="noopener noreferrer"
    clean_html = bleach.linkify(clean_html, callbacks=[
        lambda attrs, new: attrs.update({(None, 'rel'): 'noopener noreferrer', (None, 'target'): '_blank'}) or attrs
    ])
    return clean_html
