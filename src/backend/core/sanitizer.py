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
    return False

ALLOWED_PROTOCOLS = ['http', 'https', 'mailto']

def render_and_sanitize_markdown(raw_markdown: str) -> str:
    """Renders markdown to HTML and thoroughly sanitizes it."""
    if not raw_markdown:
        return ""
    # Render with standard markdown extensions
    raw_html = markdown.markdown(
        raw_markdown,
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
