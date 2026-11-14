import html
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
        if name in ['alt', 'title', 'loading', 'decoding', 'width', 'height']:
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

def _replace_balanced_tex_commands(text: str) -> str:
    """
    Replaces balanced-brace {\\displaystyle ...} and {\\textstyle ...} constructs
    (including nested braces and multiline expressions) outside inline `...` code spans.
    """
    if "{\\displaystyle" not in text and "{\\textstyle" not in text:
        return text

    out = []
    i = 0
    n = len(text)
    while i < n:
        # Preserve inline code spans `...`
        if text[i] == "`":
            tick_end = i
            while tick_end < n and text[tick_end] == "`":
                tick_end += 1
            ticks = text[i:tick_end]
            close_idx = text.find(ticks, tick_end)
            if close_idx != -1:
                out.append(text[i : close_idx + len(ticks)])
                i = close_idx + len(ticks)
                continue

        matched_cmd = None
        for cmd in ("{\\displaystyle", "{\\textstyle"):
            if text.startswith(cmd, i):
                # Ensure command is followed by whitespace or '{' or backslash/non-alpha
                next_pos = i + len(cmd)
                if next_pos >= n or not text[next_pos].isalpha():
                    matched_cmd = cmd
                    break

        if matched_cmd:
            depth = 1
            j = i + len(matched_cmd)
            while j < n and depth > 0:
                ch = text[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                j += 1
            if depth == 0:
                inner = text[i + len(matched_cmd) : j - 1].strip()
                if matched_cmd == "{\\displaystyle":
                    out.append(f'<div class="math-display">$${inner}$$</div>')
                else:
                    out.append(f'<span class="math-inline">\\({inner}\\)</span>')
                i = j
                continue

        out.append(text[i])
        i += 1

    return "".join(out)


def normalize_markdown_syntax(content: str) -> str:
    r"""
    Normalizes MediaWiki-style headings and math blocks into standard Markdown/HTML:
    - == Heading == -> ## Heading outside fenced code blocks (F08)
    - {\displaystyle ...} -> <div class="math-display">$$...$$</div> (F08)
    - {\textstyle ...} -> <span class="math-inline">\(...\)</span> (F08)
    """
    if not content:
        return ""

    # First pass: line-by-line heading normalization outside fenced code blocks,
    # grouping non-fenced segments so multiline {\displaystyle ...} blocks are preserved intact.
    segments = []
    current_prose = []
    fence = None

    for line in content.splitlines(keepends=True):
        raw_line = line.rstrip("\r\n")
        if fence:
            current_prose.append(line)
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + r"{" + str(len(fence)) + r",}[ \t]*", raw_line):
                segments.append(("code", "".join(current_prose)))
                current_prose = []
                fence = None
            continue

        fence_match = re.match(r" {0,3}(`{3,}|~{3,})", line)
        if fence_match:
            if current_prose:
                segments.append(("prose", "".join(current_prose)))
                current_prose = []
            fence = fence_match.group(1)
            current_prose.append(line)
            continue

        heading_match = re.match(r"^(={2,6})\s*(.*?)\s*\1$", raw_line)
        if heading_match:
            eq_len = len(heading_match.group(1))
            heading_text = heading_match.group(2)
            ending = "\r\n" if line.endswith("\r\n") else "\n"
            line = f"{'#' * eq_len} {heading_text}{ending}"

        current_prose.append(line)

    if current_prose:
        segments.append(("code" if fence else "prose", "".join(current_prose)))

    rendered_segments = []
    for seg_type, seg_text in segments:
        if seg_type == "code":
            rendered_segments.append(seg_text)
        else:
            rendered_segments.append(_replace_balanced_tex_commands(seg_text))

    return "".join(rendered_segments)


_MATH_SPAN_PATTERN = re.compile(
    r'<div class="math-display">\$\$([\s\S]*?)\$\$</div>'
    r'|(?<!\\)\$\$([\s\S]+?)(?<!\\)\$\$'
    r'|\\\[([\s\S]+?)\\\]'
    r'|<span class="math-inline">\\\(([\s\S]*?)\\\)</span>'
    r'|\\\(([^\r\n]+?)\\\)',
)


def _protect_math_outside_code(normalized_md: str):
    """
    Replaces math delimiters outside fenced/inline code with alphanumeric tokens
    so Python-Markdown does not corrupt underscores, asterisks, or backslashes inside TeX.
    """
    tokens = {}
    counter = 0

    def replace_in_prose(segment: str) -> str:
        nonlocal counter

        def _repl(match: re.Match) -> str:
            nonlocal counter
            g_div, g_dd, g_br, g_span, g_par = match.groups()
            if g_div is not None:
                is_display = True
                raw_tex = g_div
            elif g_dd is not None:
                is_display = True
                raw_tex = g_dd
            elif g_br is not None:
                is_display = True
                raw_tex = g_br
            elif g_span is not None:
                is_display = False
                raw_tex = g_span
            else:
                is_display = False
                raw_tex = g_par or ""

            safe_tex = html.escape(raw_tex.strip(), quote=False)
            if is_display:
                tok = f"FOLIOMATHBLOCK{counter}END"
                tokens[tok] = f'<div class="math-display">$${safe_tex}$$</div>'
            else:
                tok = f"FOLIOMATHINLINE{counter}END"
                tokens[tok] = f'<span class="math-inline">\\({safe_tex}\\)</span>'
            counter += 1
            return tok

        return _MATH_SPAN_PATTERN.sub(_repl, segment)

    # Split by fenced code blocks first, then inline code spans
    parts = re.split(r"(^ {0,3}(?:`{3,}|~{3,})[^\n]*\n[\s\S]*?^ {0,3}(?:`{3,}|~{3,})[ \t]*$)", normalized_md, flags=re.MULTILINE)
    processed_parts = []
    for idx, part in enumerate(parts):
        if idx % 2 == 1:
            processed_parts.append(part)
        else:
            inline_parts = re.split(r"(`+[^`]*?`+)", part)
            for j, ipart in enumerate(inline_parts):
                if j % 2 == 1:
                    processed_parts.append(ipart)
                else:
                    processed_parts.append(replace_in_prose(ipart))

    return "".join(processed_parts), tokens


def render_and_sanitize_markdown(raw_markdown: str) -> str:
    """Renders markdown to HTML and thoroughly sanitizes it."""
    if not raw_markdown:
        return ""
    # Normalize MediaWiki headings and math delimiters before parsing
    normalized = normalize_markdown_syntax(raw_markdown)
    protected_md, math_tokens = _protect_math_outside_code(normalized)
    # Render with standard markdown extensions
    raw_html = markdown.markdown(
        protected_md,
        extensions=['fenced_code', 'tables', 'nl2br']
    )
    for tok, replacement in math_tokens.items():
        raw_html = raw_html.replace(f"<p>{tok}</p>", replacement).replace(tok, replacement)
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
