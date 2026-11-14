import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, unquote, urljoin, urlsplit, urlunsplit

import scrapy
from bs4 import BeautifulSoup, Tag
from markdownify import MarkdownConverter

ALLOWED_IMAGE_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".svg",
    ".gif",
    ".webp",
    ".tif",
    ".tiff",
)

DECORATIVE_ANCESTOR_CLASSES = {
    "mw-editsection",
    "ambox",
    "tmbox",
    "cmbox",
    "ombox",
    "fmbox",
    "dmbox",
    "mbox-image",
    "mbox-image-div",
    "mbox-small",
    "navbox",
    "vertical-navbox",
    "sistersitebox",
    "portal",
    "portalbox",
    "metadata",
    "catlinks",
    "mw-indicators",
    "mw-indicator",
    "flagicon",
    "noprint",
    "nomobile",
    "noviewer",
    "audiodescription",
}

DECORATIVE_FILENAME_PATTERNS = (
    "ambox_",
    "padlock",
    "semi-protection",
    "full-protection",
    "lock-green",
    "lock-gray",
    "lock-gold",
    "lock-red",
    "edit-clear",
    "question_book",
    "text_document",
    "nuvola_",
    "crystal_clear",
    "commons-logo",
    "wikibooks-logo",
    "wikinews-logo",
    "wikiquote-logo",
    "wikisource-logo",
    "wikiversity-logo",
    "wikivoyage-logo",
    "wiktionary-logo",
    "wikidata-logo",
    "wikimedia-logo",
    "wiki_letter_w",
    "folder_hexagonal",
    "symbol_category_class",
    "symbol_support",
    "symbol_oppose",
    "symbol_neutral",
    "steady2",
    "increase2",
    "decrease2",
    "speaker_icon",
    "loudspeaker",
    "speakerlink",
    "disambig",
    "merge-arrows",
    "split-arrows",
    "oojs_ui_icon",
    "red_pog",
    "blue_pog",
    "green_pog",
    "locator_dot",
    "closed_access_logo",
    "open_access_logo",
    "free_to_read",
    "1x1",
    "transparent.gif",
    "blank.gif",
)

UNWANTED_SECTIONS = [
    "References",
    "See_also",
    "External_links",
    "Further_reading",
    "Notes",
    "Explanatory_notes",
    "Citations",
    "Bibliography",
]


def _is_valid_wiki_host(hostname: Optional[str]) -> bool:
    if not hostname:
        return False
    host = hostname.strip().lower().rstrip(".")
    return (
        host in {"wikimedia.org", "wikipedia.org"}
        or host.endswith(".wikimedia.org")
        or host.endswith(".wikipedia.org")
    )


def _escape_markdown_url(url: str) -> str:
    return (
        url.strip()
        .replace(" ", "%20")
        .replace("(", "%28")
        .replace(")", "%29")
        .replace('"', "%22")
    )


def _clean_markdown_alt(text: str, max_len: int = 255) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = cleaned.replace("[", "(").replace("]", ")")
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 3].rstrip() + "..."
    return cleaned


def normalize_wikimedia_image_url(
    raw_url: Optional[str],
    page_url: str = "https://en.wikipedia.org",
) -> Optional[str]:
    """
    Normalizes an image URL to HTTPS and strictly validates that its hostname
    belongs to Wikimedia/Wikipedia and points to an actual image resource.
    """
    if not raw_url or not isinstance(raw_url, str):
        return None
    candidate = raw_url.strip()
    if not candidate:
        return None
    lower_cand = candidate.lower()
    if lower_cand.startswith(("data:", "javascript:", "vbscript:", "about:", "blob:", "mailto:")):
        return None

    if candidate.startswith("//"):
        candidate = "https:" + candidate
    elif candidate.startswith("/"):
        candidate = urljoin(page_url, candidate)

    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None

    scheme = (parsed.scheme or "").lower()
    if scheme == "http" and _is_valid_wiki_host(parsed.hostname):
        scheme = "https"
    if scheme != "https":
        return None

    if not _is_valid_wiki_host(parsed.hostname):
        return None

    path = parsed.path or ""
    path_lower = path.lower()
    if not path_lower or path_lower == "/":
        return None

    rejected_path_Markers = (
        "/static/",
        "/w/resources/",
        "/wiki/special:",
        "/w/index.php",
        "centralautologin",
        "/api/rest_v1/media/math/",
        "/media/math/render/",
    )
    if any(marker in path_lower for marker in rejected_path_Markers):
        return None

    if not path_lower.endswith(ALLOWED_IMAGE_EXTENSIONS):
        return None

    # Strip tracking query params such as utm_source / utm_campaign / utm_content
    clean_query = ""
    if parsed.query:
        kept_params = [
            (k, v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if not k.lower().startswith("utm_")
        ]
        if kept_params:
            clean_query = urlencode(kept_params)

    host_norm = (parsed.hostname or "").lower()
    if host_norm == "thumb.wikimedia.org" and path.startswith("/wikipedia/"):
        host_norm = "upload.wikimedia.org"

    normalized = urlunsplit((scheme, host_norm, path, clean_query, ""))
    normalized = _escape_markdown_url(normalized)
    if len(normalized) > 1000:
        return None
    return normalized


def _parse_int_dimension(val: Any) -> Optional[int]:
    if val is None:
        return None
    s = str(val).strip().lower()
    if s.endswith("px"):
        s = s[:-2].strip()
    m = re.match(r"^(\d+)(?:\.\d+)?$", s)
    if m:
        return int(m.group(1))
    return None


def _extract_img_dimensions(img_tag: Tag) -> Tuple[Optional[int], Optional[int]]:
    width = _parse_int_dimension(img_tag.get("width"))
    height = _parse_int_dimension(img_tag.get("height"))

    style = img_tag.get("style") or ""
    if width is None and style:
        m_w = re.search(r"(?:^|;|\s)width\s*:\s*(\d+(?:\.\d+)?)px", style, re.IGNORECASE)
        if m_w:
            width = int(float(m_w.group(1)))
    if height is None and style:
        m_h = re.search(r"(?:^|;|\s)height\s*:\s*(\d+(?:\.\d+)?)px", style, re.IGNORECASE)
        if m_h:
            height = int(float(m_h.group(1)))

    return width, height


def select_best_image_url(img_tag: Tag, page_url: str = "https://en.wikipedia.org") -> Optional[str]:
    """
    Selects a reasonable-sized HTTPS image URL from src, data-src, or srcset
    without guessing or string-concatenating thumbnail paths.
    """
    primary_raw = img_tag.get("src") or img_tag.get("data-src")
    primary_url = normalize_wikimedia_image_url(primary_raw, page_url)

    srcset_raw = img_tag.get("srcset") or img_tag.get("data-srcset") or ""
    srcset_candidates: List[Tuple[float, str]] = []
    if srcset_raw and isinstance(srcset_raw, str):
        for entry in srcset_raw.split(","):
            parts = entry.strip().split()
            if not parts:
                continue
            cand_url = normalize_wikimedia_image_url(parts[0], page_url)
            if not cand_url:
                continue
            score = 1.0
            if len(parts) > 1:
                desc = parts[1].strip().lower()
                if desc.endswith("x"):
                    try:
                        mult = float(desc[:-1])
                        if mult <= 2.5:
                            score = mult
                    except ValueError:
                        pass
                elif desc.endswith("w"):
                    try:
                        w_val = float(desc[:-1])
                        if w_val <= 1000:
                            score = w_val / 250.0
                    except ValueError:
                        pass
            srcset_candidates.append((score, cand_url))

    width, _ = _extract_img_dimensions(img_tag)
    if srcset_candidates:
        # Sort by preference for crisp 1.5x/2x thumbnails when base width is small
        srcset_candidates.sort(key=lambda item: item[0], reverse=True)
        if primary_url is None or (width is not None and width <= 360):
            return srcset_candidates[0][1]

    return primary_url


def is_valid_content_image(img_tag: Tag, norm_url: str) -> bool:
    """
    Determines whether an <img> tag is a legitimate article content illustration
    rather than a tracking pixel, UI icon, math fallback, or decorative badge.
    """
    if not norm_url:
        return False

    img_classes = set(img_tag.get("class") or [])
    if img_classes.intersection(
        {"mwe-math-fallback-image-inline", "mwe-math-fallback-image-display", "noviewer"}
    ):
        return False

    if img_tag.find_parent(class_="mwe-math-element") is not None:
        return False

    for parent in img_tag.parents:
        if not isinstance(parent, Tag):
            continue
        p_classes = set(parent.get("class") or [])
        if p_classes.intersection(DECORATIVE_ANCESTOR_CLASSES):
            return False

    width, height = _extract_img_dimensions(img_tag)
    if width is not None and width < 45:
        return False
    if height is not None and height < 45:
        return False

    file_w = _parse_int_dimension(img_tag.get("data-file-width"))
    file_h = _parse_int_dimension(img_tag.get("data-file-height"))
    if file_w is not None and file_w < 45:
        return False
    if file_h is not None and file_h < 45:
        return False

    path_lower = unquote(urlsplit(norm_url).path).lower()
    filename_lower = path_lower.rsplit("/", 1)[-1]
    if any(pat in filename_lower or pat in path_lower for pat in DECORATIVE_FILENAME_PATTERNS):
        return False

    return True


def _humanize_filename_from_url(url_or_href: str) -> str:
    path = unquote(urlsplit(url_or_href).path)
    basename = path.rsplit("/", 1)[-1]
    basename = re.sub(r"^\d+px--?", "", basename)
    if basename.lower().startswith("file:"):
        basename = basename[5:]
    # Strip extension(s) like .svg.png or .jpg
    basename = re.sub(r"\.(?:svg\.png|webp\.png|tif\.jpg|jpg|jpeg|png|svg|gif|webp|tif|tiff)$", "", basename, flags=re.IGNORECASE)
    basename = basename.replace("_", " ").strip()
    return basename


def _is_meaningful_alt(alt_text: str) -> bool:
    if not alt_text:
        return False
    cleaned = alt_text.strip()
    if len(cleaned) < 3:
        return False
    lower = cleaned.lower()
    if lower in {"icon", "image", "photo", "diagram", "picture", "thumbnail", "stub", "logo"}:
        return False
    if re.match(r"^(?:file:|\d+px-)?[^\s]+\.(?:jpg|jpeg|png|svg|gif|webp|tif|tiff)$", lower):
        return False
    return True


def _extract_file_source_url(img_tag: Tag, page_url: str) -> Optional[str]:
    parent_a = img_tag.find_parent("a", href=True)
    if not parent_a:
        return None
    href = (parent_a.get("href") or "").strip()
    if not href:
        return None
    full_url = urljoin(page_url, href)
    try:
        parsed = urlsplit(full_url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not _is_valid_wiki_host(parsed.hostname):
        return None
    if "/wiki/File:" in parsed.path or "/wiki/Special:FilePath/" in parsed.path:
        scheme = "https"
        clean_url = urlunsplit((scheme, (parsed.hostname or "").lower(), parsed.path, "", ""))
        return _escape_markdown_url(clean_url)
    return None


def _extract_image_caption(img_tag: Tag) -> Tuple[str, Optional[Tag]]:
    """
    Finds the closest caption element associated with an image and returns
    its cleaned text and the caption Tag.
    """
    # 1. Inside <figure>
    fig = img_tag.find_parent("figure")
    if fig:
        figcap = fig.find("figcaption")
        if figcap:
            return re.sub(r"\s+", " ", figcap.get_text(" ", strip=True)).strip(), figcap

    # 2. Inside multi-image .tsingle
    tsingle = img_tag.find_parent(class_="tsingle")
    if tsingle:
        tcap = tsingle.find(class_="thumbcaption")
        if tcap:
            for mag in tcap.select(".magnify"):
                mag.decompose()
            return re.sub(r"\s+", " ", tcap.get_text(" ", strip=True)).strip(), tcap

    # 3. Inside .thumbinner / .thumb
    thumbinner = img_tag.find_parent(class_=["thumbinner", "thumb"])
    if thumbinner:
        tcap = thumbinner.find(class_="thumbcaption")
        if tcap:
            for mag in tcap.select(".magnify"):
                mag.decompose()
            return re.sub(r"\s+", " ", tcap.get_text(" ", strip=True)).strip(), tcap

    # 4. Inside gallerybox
    gbox = img_tag.find_parent(class_="gallerybox")
    if gbox:
        gtext = gbox.find(class_="gallerytext")
        if gtext:
            return re.sub(r"\s+", " ", gtext.get_text(" ", strip=True)).strip(), gtext

    # 5. Inside infobox cell/row
    td = img_tag.find_parent(["td", "th"])
    if td:
        icap = td.find(class_="infobox-caption")
        if icap:
            return re.sub(r"\s+", " ", icap.get_text(" ", strip=True)).strip(), icap

    return "", None


class WikiMarkdownConverter(MarkdownConverter):
    """
    Custom MarkdownConverter that:
    - Always preserves validated <img> tags even when nested inside table cells or inline spans.
    - Strips ordinary Wikipedia prose <a> links while preserving explicit File source links.
    """

    def convert_img(self, el: Tag, text: str, parent_tags: Any) -> str:
        src = (el.attrs.get("src") or "").strip()
        if not src:
            return ""
        alt = _clean_markdown_alt(el.attrs.get("alt") or "", max_len=240)
        return f"![{alt}]({src})"

    def convert_a(self, el: Tag, text: str, parent_tags: Any) -> str:
        if el.attrs.get("data-wiki-file-source") == "1":
            href = (el.attrs.get("href") or "").strip()
            label = (text or "").strip() or "Image file"
            if href:
                return f"[{label}]({href})"
        return text

    def convert_figcaption(self, el: Tag, text: str, parent_tags: Any) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""
        return f"\n\n{cleaned}\n\n"


def _build_replacement_figure_node(
    soup: BeautifulSoup,
    img_url: str,
    alt_text: str,
    caption_text: str,
    file_source_url: Optional[str],
) -> Tag:
    wrapper = soup.new_tag("div", attrs={"class": "wiki-extracted-figure"})
    p_img = soup.new_tag("p")
    new_img = soup.new_tag("img", attrs={"src": img_url, "alt": alt_text, "data-wiki-valid": "1"})
    p_img.append(new_img)
    wrapper.append(p_img)

    if caption_text or file_source_url:
        p_cap = soup.new_tag("p")
        em = soup.new_tag("em")
        safe_cap = caption_text.replace("*", "\\*").replace("_", "\\_").strip()
        if safe_cap:
            em.append(safe_cap)
        if file_source_url:
            if safe_cap:
                em.append(" (")
            else:
                em.append("(")
            src_link = soup.new_tag(
                "a",
                attrs={"href": file_source_url, "data-wiki-file-source": "1"},
            )
            src_link.string = "Image source"
            em.append(src_link)
            em.append(")")
        p_cap.append(em)
        wrapper.append(p_cap)

    return wrapper


def extract_clean_summary(markdown_text: str, fallback_title: str = "", max_len: int = 400) -> str:
    """
    Extracts a clean prose paragraph from Markdown content, skipping headings,
    image Markdown syntax, image URLs, standalone captions, tables, and hatnotes.
    """
    if not markdown_text:
        return fallback_title

    hatnote_prefixes = (
        "for other uses",
        "for the ",
        "this article is about",
        "not to be confused with",
        "main article:",
        "see also:",
        "further information:",
    )

    candidates: List[str] = []
    for raw_block in re.split(r"\n\s*\n", markdown_text):
        block = raw_block.strip()
        if not block:
            continue

        # Remove inline image markdown and standalone file source links
        block_no_img = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", block)
        block_no_img = re.sub(r"\(\[Image source\]\([^)]+\)\)", "", block_no_img)
        block_no_img = re.sub(r"\[Image source\]\([^)]+\)", "", block_no_img).strip()
        if not block_no_img:
            continue

        lines = [ln.strip() for ln in block_no_img.splitlines() if ln.strip()]
        prose_lines = []
        for ln in lines:
            if ln.startswith(("#", "|", "```", "~~~", "* ", "- ", "> ")):
                continue
            if re.match(r"^={2,6}\s+.*\s+={2,6}$", ln):
                continue
            if "https://upload.wikimedia.org" in ln or "https://thumb.wikimedia.org" in ln:
                continue
            if ln.startswith("*") and ln.endswith("*") and len(ln) < 220:
                # Likely a standalone italicized figure caption
                continue
            prose_lines.append(ln)

        if not prose_lines:
            continue

        paragraph = re.sub(r"\s+", " ", " ".join(prose_lines)).strip()
        # Strip basic markdown emphasis markers for clean plain-text summary
        plain = re.sub(r"\*\*([^*]+)\*\*", r"\1", paragraph)
        plain = re.sub(r"\*([^*]+)\*", r"\1", plain)
        plain = plain.strip()
        if not plain:
            continue

        low = plain.lower()
        if any(low.startswith(prefix) for prefix in hatnote_prefixes) or "redirects here" in low:
            continue

        candidates.append(plain)
        # Prefer first substantial prose paragraph (>= 80 chars and contains a sentence period)
        if len(plain) >= 80 and "." in plain:
            return plain[:max_len]

    if candidates:
        return candidates[0][:max_len]
    return fallback_title[:max_len]


def extract_article_content_and_images(
    content_html: str,
    page_url: str,
    title: str,
) -> Dict[str, Any]:
    """
    Cleans Wikipedia parser HTML, normalizes and filters content images,
    selects a cover image + alt text, and produces Markdown with inline images,
    captions, File source links, and preserved TeX math.
    """
    if not content_html:
        return {
            "text": "",
            "summary": title,
            "cover_image_url": None,
            "cover_image_alt": None,
        }

    soup = BeautifulSoup(content_html, "html.parser")

    # 1. Remove edit controls, citation superscripts, scripts/styles, hatnotes, and short descriptions
    for selector in (
        ".mw-editsection",
        "sup.reference",
        ".shortdescription",
        ".hatnote",
        "style",
        "script",
        "link",
        "meta",
        ".mw-indicators",
        ".mw-indicator",
    ):
        for el in soup.select(selector):
            el.decompose()

    # 2. Remove trailing reference/navigation sections (supports both modern <section>/<div.mw-heading> and legacy <h2><span#id>)
    for section_id in UNWANTED_SECTIONS:
        heading_el = soup.find(id=section_id)
        if not heading_el:
            continue
        h_tag = heading_el if heading_el.name in ("h2", "h3") else heading_el.find_parent(["h2", "h3"])
        if not h_tag:
            continue

        sec = h_tag.find_parent("section")
        if sec and sec.find(["h2", "h3"]) == h_tag:
            if h_tag.name == "h2":
                for sib in list(sec.find_next_siblings()):
                    sib.decompose()
            sec.decompose()
            continue

        block = h_tag.parent if (h_tag.parent and "mw-heading" in (h_tag.parent.get("class") or [])) else h_tag
        for sib in list(block.find_next_siblings()):
            sib.decompose()
        block.decompose()

    # 3. Remove decorative / non-article boxes while keeping infoboxes, tables, and image thumbs
    unwanted_box_classes = {
        "navbox",
        "vertical-navbox",
        "sidebar",
        "reflist",
        "metadata",
        "mw-empty-elt",
        "ambox",
        "tmbox",
        "cmbox",
        "ombox",
        "fmbox",
        "dmbox",
        "mbox-small",
        "sistersitebox",
        "portal",
        "portalbox",
        "catlinks",
        "authority-control",
        "toc",
    }
    for box in list(soup.find_all(["div", "table", "aside", "ul"])):
        if not isinstance(box, Tag) or box.attrs is None:
            continue
        classes = set(box.get("class") or [])
        if "infobox" in classes or "wikitable" in classes or "thumb" in classes:
            continue
        if classes.intersection(unwanted_box_classes):
            box.decompose()

    # 4. Preserve math formulas: remove math fallback <img> tags so <math> TeX annotations remain intact
    for math_img in list(
        soup.select(
            ".mwe-math-element img, img.mwe-math-fallback-image-inline, img.mwe-math-fallback-image-display"
        )
    ):
        math_img.decompose()
    for img in list(soup.find_all("img")):
        src_val = (img.get("src") or "").lower()
        if "/media/math/render/" in src_val:
            img.decompose()

    # 5. Convert <video> elements with valid Wikimedia poster thumbnails into <img> or decompose
    for video in list(soup.find_all("video")):
        poster_url = normalize_wikimedia_image_url(video.get("poster"), page_url)
        if poster_url:
            alt_v = video.get_text(" ", strip=True) or title
            replacement_img = soup.new_tag(
                "img",
                attrs={"src": poster_url, "alt": alt_v, "width": video.get("width") or "250", "height": video.get("height") or "160"},
            )
            video.replace_with(replacement_img)
        else:
            video.decompose()
    for audio in list(soup.find_all("audio")):
        audio.decompose()

    # 6. Inspect all remaining <img> elements, validate & collect metadata
    first_h2 = soup.find("h2")
    all_elements_order = list(soup.descendants)
    first_h2_pos = all_elements_order.index(first_h2) if first_h2 in all_elements_order else len(all_elements_order)

    valid_img_records: List[Dict[str, Any]] = []
    for img in list(soup.find_all("img")):
        if not isinstance(img, Tag) or img.attrs is None:
            continue
        norm_url = select_best_image_url(img, page_url)
        if not norm_url or not is_valid_content_image(img, norm_url):
            # Remove decorative/invalid image
            fig_parent = img.find_parent("figure")
            img.decompose()
            if fig_parent and not fig_parent.find("img"):
                fig_parent.decompose()
            continue

        caption_text, caption_el = _extract_image_caption(img)
        file_source_url = _extract_file_source_url(img, page_url)
        raw_alt = (img.get("alt") or "").strip()

        if _is_meaningful_alt(raw_alt):
            best_alt = _clean_markdown_alt(raw_alt, max_len=255)
        elif caption_text:
            best_alt = _clean_markdown_alt(caption_text, max_len=255)
        else:
            human_name = _humanize_filename_from_url(file_source_url or norm_url)
            best_alt = _clean_markdown_alt(human_name or title, max_len=255)

        width, height = _extract_img_dimensions(img)
        in_infobox = img.find_parent(class_="infobox") is not None
        try:
            pos = all_elements_order.index(img)
        except ValueError:
            pos = first_h2_pos + 1
        in_lead = pos < first_h2_pos

        valid_img_records.append(
            {
                "img": img,
                "url": norm_url,
                "alt": best_alt,
                "caption": caption_text,
                "caption_el": caption_el,
                "file_source_url": file_source_url,
                "width": width,
                "height": height,
                "in_infobox": in_infobox,
                "in_lead": in_lead,
                "pos": pos,
            }
        )

    # 7. Select cover_image_url and cover_image_alt
    cover_record: Optional[Dict[str, Any]] = None
    if valid_img_records:
        # Prefer lead or infobox images with good size (>= 120x80 or unspecified)
        lead_or_infobox = [
            r
            for r in valid_img_records
            if (r["in_lead"] or r["in_infobox"])
            and (r["width"] is None or r["width"] >= 120)
            and (r["height"] is None or r["height"] >= 80)
        ]
        if lead_or_infobox:
            cover_record = lead_or_infobox[0]
        else:
            sized_body = [
                r
                for r in valid_img_records
                if (r["width"] is None or r["width"] >= 120)
                and (r["height"] is None or r["height"] >= 80)
            ]
            cover_record = sized_body[0] if sized_body else valid_img_records[0]

    cover_image_url = cover_record["url"] if cover_record else None
    cover_image_alt = (
        _clean_markdown_alt(cover_record["alt"] or cover_record["caption"] or title, max_len=255)
        if cover_record
        else None
    )

    # 8. Transform valid images in DOM into clean Markdown-ready figure blocks
    # Avoid repeating the cover image in the body when multiple images exist
    seen_urls = set()
    skip_cover_in_body = bool(cover_record and len(valid_img_records) > 1)

    for rec in valid_img_records:
        img = rec["img"]
        if img.parent is None:
            continue

        url = rec["url"]
        is_skipped_cover = skip_cover_in_body and rec is cover_record
        if is_skipped_cover or url in seen_urls:
            seen_urls.add(url)
            # Cleanly remove duplicate/lead-cover image container so it isn't repeated in body
            fig = img.find_parent("figure")
            tsingle = img.find_parent(class_="tsingle")
            thumb = img.find_parent(class_=["thumb", "gallerybox"])
            if fig:
                fig.decompose()
            elif tsingle:
                tsingle.decompose()
            elif thumb:
                thumb.decompose()
            else:
                if rec["caption_el"] and rec["caption_el"].parent is not None:
                    rec["caption_el"].decompose()
                img.decompose()
            continue

        seen_urls.add(url)
        block_node = _build_replacement_figure_node(
            soup=soup,
            img_url=url,
            alt_text=rec["alt"],
            caption_text=rec["caption"],
            file_source_url=rec["file_source_url"],
        )

        # If only 1 image exists in the whole article and it's in the lead before the first paragraph,
        # place it after the first prose paragraph so the article doesn't start with a duplicate of the cover
        fig = img.find_parent("figure")
        tsingle = img.find_parent(class_="tsingle")
        gbox = img.find_parent(class_="gallerybox")
        thumb = img.find_parent(class_="thumb")
        infobox = img.find_parent(class_="infobox")

        target_container = fig or tsingle or gbox or thumb
        if infobox is not None:
            infobox.insert_before(block_node)
            if rec["caption_el"] and rec["caption_el"].parent is not None:
                rec["caption_el"].decompose()
            img.decompose()
        elif target_container is not None:
            target_container.replace_with(block_node)
        else:
            if rec["caption_el"] and rec["caption_el"].parent is not None:
                rec["caption_el"].decompose()
            img.replace_with(block_node)

        if rec is cover_record and rec["in_lead"] and len(valid_img_records) == 1:
            first_p = None
            for p in soup.find_all("p"):
                if p.find_parent(class_="wiki-extracted-figure") is not None:
                    continue
                if len(p.get_text(strip=True)) >= 60:
                    first_p = p
                    break
            if first_p is not None:
                first_p.insert_after(block_node)

    # Convert cleaned DOM to Markdown
    converter = WikiMarkdownConverter(heading_style="ATX")
    full_text = converter.convert_soup(soup).strip()
    # Collapse excessive blank lines
    full_text = re.sub(r"\n{3,}", "\n\n", full_text).strip()
    summary = extract_clean_summary(full_text, fallback_title=title)

    return {
        "text": full_text,
        "summary": summary,
        "cover_image_url": cover_image_url,
        "cover_image_alt": cover_image_alt,
    }


class WikipediaSpider(scrapy.Spider):
    name = "wiki_spider"
    allowed_domains = ["en.wikipedia.org"]
    start_urls = [
        "https://en.wikipedia.org/wiki/Artificial_intelligence",
        "https://en.wikipedia.org/wiki/Deep_learning",
        "https://en.wikipedia.org/wiki/Machine_learning",
        "https://en.wikipedia.org/wiki/Natural_language_processing",
        "https://en.wikipedia.org/wiki/Computer_vision",
        "https://en.wikipedia.org/wiki/Reinforcement_learning",
        "https://en.wikipedia.org/wiki/Neural_network_(machine_learning)",
        "https://en.wikipedia.org/wiki/Large_language_model",
    ]
    custom_settings = {
        "DEPTH_LIMIT": 4,
        "CLOSESPIDER_ITEMCOUNT": 50000,
        "JOBDIR": "crawls/wiki50k",
    }

    @classmethod
    def update_settings(cls, settings):
        super().update_settings(settings)
        # When user specifies a custom output feed via -o / -O on the CLI,
        # Scrapy merges it into settings["FEEDS"]. Delete the default dataset
        # key in-place so sample/test crawls never append to wiki_crawler_dataset.jsonl.
        default_feed = "../data/raw/wiki_crawler_dataset.jsonl"
        if "FEEDS" in settings and len(settings["FEEDS"]) > 1 and default_feed in settings["FEEDS"]:
            del settings["FEEDS"][default_feed]

    def __init__(
        self,
        urls: Optional[str] = None,
        url_file: Optional[str] = None,
        follow_links: Optional[str] = None,
        max_items: Optional[str] = None,
        *args: Any,
        **kwargs: Any,
    ):
        super(WikipediaSpider, self).__init__(*args, **kwargs)
        self.scraped_count = 0
        self.max_items = int(max_items) if max_items and str(max_items).strip().isdigit() else None

        custom_urls: List[str] = []
        if urls:
            for raw in re.split(r"[,;\s]+", str(urls).strip()):
                u = self._normalize_input_wiki_url(raw)
                if u:
                    custom_urls.append(u)

        if url_file:
            path = Path(url_file)
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    u = self._normalize_input_wiki_url(line)
                    if u:
                        custom_urls.append(u)

        self.is_custom_url_run = bool(custom_urls)
        if custom_urls:
            self.start_urls = custom_urls

        if follow_links is not None:
            self.follow_links = str(follow_links).strip().lower() in ("1", "true", "yes", "y")
        else:
            # Default to not following links when explicit sample URLs are provided
            self.follow_links = not self.is_custom_url_run

    @staticmethod
    def _normalize_input_wiki_url(raw: str) -> Optional[str]:
        val = (raw or "").strip()
        if not val or val.startswith("#"):
            return None
        if val.startswith(("http://", "https://")):
            return val
        slug = val.lstrip("/").replace(" ", "_")
        if slug.startswith("wiki/"):
            return f"https://en.wikipedia.org/{slug}"
        return f"https://en.wikipedia.org/wiki/{slug}"

    def start_requests(self):
        for url in self.start_urls:
            yield scrapy.Request(
                url,
                callback=self.parse,
                dont_filter=self.is_custom_url_run,
            )

    def parse(self, response):
        if self.max_items is not None and self.scraped_count >= self.max_items:
            return

        title_element = response.css("span.mw-page-title-main::text").get()
        if not title_element:
            title_element = response.css("h1#firstHeading *::text").get()
        if not title_element:
            title_element = response.css("h1#firstHeading::text").get()
        title = title_element.strip() if title_element else "Unknown title"

        content_html = response.css("#mw-content-text div.mw-parser-output").get()
        if not content_html:
            candidates = response.css("div.mw-parser-output").getall()
            content_html = max(candidates, key=len) if candidates else ""

        extracted = extract_article_content_and_images(
            content_html=content_html,
            page_url=response.url,
            title=title,
        )
        full_text = extracted["text"]

        if full_text and len(full_text) > 100:
            self.scraped_count += 1
            if self.scraped_count % 500 == 0:
                self.logger.info(f"[PROGRESS] Da crawl {self.scraped_count} bai")

            stable_id = str(uuid.uuid5(uuid.NAMESPACE_URL, response.url.strip()))
            yield {
                "id": stable_id,
                "title": title,
                "url": response.url,
                "text": full_text,
                "summary": extracted["summary"],
                "cover_image_url": extracted["cover_image_url"],
                "cover_image_alt": extracted["cover_image_alt"],
            }

        if self.follow_links and (self.max_items is None or self.scraped_count < self.max_items):
            all_links = response.css("#mw-content-text div.mw-parser-output a::attr(href)").getall()
            for link in all_links:
                if link.startswith("/wiki/") and not any(x in link for x in [":", "#", "Main_Page"]):
                    yield scrapy.Request(url=urljoin(response.url, link), callback=self.parse)
