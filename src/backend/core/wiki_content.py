"""Remove section-edit controls left in Markdown by older Wikipedia crawls."""

import re
from typing import Optional
from urllib.parse import urlsplit


def clean_wikipedia_content(content: str, source_url: Optional[str]) -> str:
    """Remove standalone edit labels after headings, preserving prose and code."""
    try:
        source = urlsplit(source_url or "")
        host = (source.hostname or "").lower()
    except ValueError:
        return content
    if source.scheme not in ("http", "https") or not (
        host == "wikipedia.org" or host.endswith(".wikipedia.org")
    ):
        return content

    result = []
    fence = None
    after_heading = False
    removed_marker = False
    for line in content.splitlines(keepends=True):
        if fence:
            result.append(line)
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + r"{" + str(len(fence)) + r",}[ \t]*", line.rstrip("\r\n")):
                fence = None
            continue
        fence_match = re.match(r" {0,3}(`{3,}|~{3,})", line)
        if fence_match:
            fence = fence_match.group(1)
            after_heading = False
            removed_marker = False
            result.append(line)
            continue
        if not line.strip():
            if not removed_marker:
                result.append(line)
            continue
        if after_heading and re.fullmatch(r" {0,3}\[edit(?: source)?\][ \t]*", line.rstrip("\r\n")):
            removed_marker = True
            continue
        after_heading = bool(re.match(r" {0,3}#{1,6}[ \t]+\S", line))
        removed_marker = False
        result.append(line)
    return "".join(result)
