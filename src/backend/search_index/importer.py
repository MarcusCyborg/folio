import json
import re
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlsplit
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.backend.models.document import Document, DocumentTag
from src.backend.models.taxonomy import Category, Tag
from src.backend.models.auth import User
from src.backend.search_index.outbox import record_revision_and_outbox_job
from src.backend.core.wiki_content import clean_wikipedia_content


def generate_doc_uuid_from_url(url: str) -> str:
    """Generates a reproducible UUIDv5 identifier derived from the canonical URL namespace."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, url.strip()))


def _strip_markdown_images_and_links(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    cleaned = re.sub(r"\(\[Image source\]\([^)]+\)\)", "", cleaned)
    cleaned = re.sub(r"\[Image source\]\([^)]+\)", "", cleaned)
    cleaned = re.sub(r"https?://(?:upload|thumb)\.wikimedia\.org/\S+", "", cleaned)
    cleaned = re.sub(r"//(?:upload|thumb)\.wikimedia\.org/\S+", "", cleaned)
    return cleaned.strip()


def extract_prose_summary(content: str, title: str, raw_summary: str = "", max_len: int = 400) -> str:
    """
    Produces a clean plain-text summary free of Markdown image syntax or image URLs.
    """
    if raw_summary:
        cleaned_raw = _strip_markdown_images_and_links(raw_summary)
        cleaned_raw = re.sub(r"\s+", " ", cleaned_raw).strip()
        if cleaned_raw and not cleaned_raw.startswith("!["):
            return cleaned_raw[:max_len]

    if not content:
        return (title or "")[:max_len]

    fallback_line = ""
    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("![", "#", "|", "```", "~~~", ">")):
            continue
        if re.match(r"^={2,6}\s+.*\s+={2,6}$", stripped):
            continue
        no_img = _strip_markdown_images_and_links(stripped)
        if not no_img:
            continue
        if no_img.startswith("*") and no_img.endswith("*") and len(no_img) < 220:
            # Skip standalone italicized image caption lines
            continue
        plain = re.sub(r"\*\*([^*]+)\*\*", r"\1", no_img)
        plain = re.sub(r"\*([^*]+)\*", r"\1", plain)
        plain = re.sub(r"\s+", " ", plain).strip()
        if not plain:
            continue
        if not fallback_line:
            fallback_line = plain
        if len(plain) >= 60:
            return plain[:max_len]

    return (fallback_line or title or "")[:max_len]


def _normalize_cover_url(raw_url: Optional[str]) -> Optional[str]:
    if not raw_url or not isinstance(raw_url, str):
        return None
    val = raw_url.strip()
    if not val:
        return None
    if val.startswith("//"):
        val = "https:" + val
    if val.startswith("/assets/"):
        return val[:1000]
    try:
        parsed = urlsplit(val)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if parsed.scheme == "http" and (
        parsed.hostname.endswith(".wikimedia.org") or parsed.hostname.endswith(".wikipedia.org")
    ):
        val = "https://" + val[len("http://") :]
    if len(val) > 1000 or '"' in val or "'" in val:
        return None
    return val


def _extract_cover_from_item(item: Dict[str, Any], title: str, content: str = "") -> Tuple[Optional[str], Optional[str]]:
    cover_url = _normalize_cover_url(item.get("cover_image_url"))
    cover_alt = (item.get("cover_image_alt") or "").strip() if isinstance(item.get("cover_image_alt"), str) else ""

    if not cover_url and content:
        m = re.search(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)", content)
        if m:
            cand_alt, cand_url = m.group(1).strip(), m.group(2).strip()
            norm_cand = _normalize_cover_url(cand_url)
            if norm_cand:
                cover_url = norm_cand
                if not cover_alt and cand_alt:
                    cover_alt = cand_alt

    if not cover_url:
        return None, None

    final_alt = re.sub(r"\s+", " ", cover_alt or title or "Article cover image").strip()
    if len(final_alt) > 255:
        final_alt = final_alt[:252].rstrip() + "..."
    return cover_url, final_alt


class CorpusImporter:
    """
    Importer for legacy JSON/JSONL corpus datasets.
    Maps source URL -> Folio Document ID idempotently, validates attribution & license,
    protects against overwriting user edits, supports targeted cover image backfill,
    and generates duplicate/conflict reports.
    """

    def __init__(self, db: Session, dry_run: bool = False):
        self.db = db
        self.dry_run = dry_run

    @staticmethod
    def load_raw_records(file_path: Path) -> Tuple[List[Dict[str, Any]], int]:
        """Loads items from either .json or .jsonl, counting malformed lines."""
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Corpus file not found: {path}")

        records = []
        bad_lines = 0

        if path.suffix.lower() == ".jsonl":
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            records.append(obj)
                    except json.JSONDecodeError:
                        bad_lines += 1
        else:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    records = data
                elif isinstance(data, dict):
                    records = [data]

        return records, bad_lines

    def import_corpus(
        self,
        file_path: Path,
        batch_size: int = 100,
        default_author: str = "Wikipedia contributors",
        default_license: str = "CC BY-SA 4.0",
        backfill_images: bool = False,
    ) -> Dict[str, Any]:
        """
        Parses corpus file, generates duplicate and conflict reports,
        and optionally ingests new documents (or backfills missing cover images
        for existing documents when backfill_images=True) into PostgreSQL.
        """
        records, bad_lines = self.load_raw_records(file_path)

        # Existing DB lookups
        existing_docs_by_url = {
            doc.source_url: doc
            for doc in self.db.query(Document).filter(Document.source_url.is_not(None)).all()
        }
        existing_docs_by_id = {
            doc.id: doc for doc in self.db.query(Document).all()
        }
        categories_by_slug = {c.slug: c for c in self.db.query(Category).all()}
        tags_by_slug = {t.slug: t for t in self.db.query(Tag).all()}

        # Default system user for created_by attribution
        admin_user = self.db.query(User).filter(User.username == "admin").first()
        admin_id = admin_user.id if admin_user else None

        seen_urls_in_file: Dict[str, int] = {}

        report: Dict[str, Any] = {
            "file": str(file_path),
            "dry_run": self.dry_run,
            "backfill_images": backfill_images,
            "total_scanned": len(records),
            "bad_lines": bad_lines,
            "valid_records": 0,
            "invalid_records": [],
            "duplicates_in_file": [],
            "conflicts_with_db": [],
            "existing_preserved": [],
            "to_insert": [],
            "to_backfill": [],
            "backfill_skipped": [],
            "attribution_verified": 0,
            "license_verified": 0,
            "inserted_count": 0,
            "preserved_count": 0,
            "would_update_count": 0,
            "updated_count": 0,
            "skipped_count": 0,
        }

        now = datetime.now(timezone.utc)
        to_create_docs = []
        to_backfill_docs: List[Tuple[Document, str, str]] = []

        for idx, item in enumerate(records, start=1):
            source_url = (item.get("source_url") or item.get("url") or "").strip()
            title = (item.get("title") or "").strip()
            content = (item.get("content") or item.get("text") or "").strip()
            content = clean_wikipedia_content(content, source_url)
            raw_summary = (item.get("summary") or "").strip()

            # Validate minimum requirements
            if not source_url:
                report["invalid_records"].append({"index": idx, "reason": "Missing source URL"})
                continue
            if not title:
                report["invalid_records"].append({"index": idx, "url": source_url, "reason": "Missing title"})
                continue
            if not content:
                report["invalid_records"].append({"index": idx, "url": source_url, "reason": "Missing content"})
                continue

            summary = extract_prose_summary(content, title, raw_summary=raw_summary, max_len=400)
            cover_image_url, cover_image_alt = _extract_cover_from_item(item, title=title, content=content)

            # Check in-file duplicate source URLs
            if source_url in seen_urls_in_file:
                report["duplicates_in_file"].append({
                    "url": source_url,
                    "first_index": seen_urls_in_file[source_url],
                    "duplicate_index": idx,
                })
                continue
            seen_urls_in_file[source_url] = idx
            report["valid_records"] += 1

            # Validate license and attribution
            source_license = (item.get("source_license") or default_license).strip()
            source_attrib = (item.get("source_attribution") or default_author).strip()
            author = (item.get("author") or default_author).strip()

            if source_license:
                report["license_verified"] += 1
            if source_attrib:
                report["attribution_verified"] += 1

            # Check if source_url already exists in PostgreSQL
            if source_url in existing_docs_by_url:
                existing_doc = existing_docs_by_url[source_url]
                if backfill_images:
                    if existing_doc.deleted_at is not None:
                        report["backfill_skipped"].append({
                            "url": source_url,
                            "document_id": existing_doc.id,
                            "title": existing_doc.title,
                            "reason": "soft_deleted",
                        })
                        report["existing_preserved"].append({
                            "url": source_url,
                            "document_id": existing_doc.id,
                            "title": existing_doc.title,
                            "action": "skipped_soft_deleted",
                        })
                        continue

                    if (existing_doc.cover_image_url or "").strip():
                        report["backfill_skipped"].append({
                            "url": source_url,
                            "document_id": existing_doc.id,
                            "title": existing_doc.title,
                            "reason": "already_has_cover_image",
                        })
                        report["existing_preserved"].append({
                            "url": source_url,
                            "document_id": existing_doc.id,
                            "title": existing_doc.title,
                            "action": "preserved_existing_cover_image",
                        })
                        continue

                    if not cover_image_url:
                        report["backfill_skipped"].append({
                            "url": source_url,
                            "document_id": existing_doc.id,
                            "title": existing_doc.title,
                            "reason": "no_valid_cover_image_in_source",
                        })
                        report["existing_preserved"].append({
                            "url": source_url,
                            "document_id": existing_doc.id,
                            "title": existing_doc.title,
                            "action": "skipped_no_source_cover",
                        })
                        continue

                    target_alt = _extract_cover_from_item(
                        {"cover_image_url": cover_image_url, "cover_image_alt": cover_image_alt},
                        title=existing_doc.title or title,
                    )[1] or (existing_doc.title or title)[:255]

                    report["to_backfill"].append({
                        "document_id": existing_doc.id,
                        "url": source_url,
                        "title": existing_doc.title,
                        "cover_image_url": cover_image_url,
                        "cover_image_alt": target_alt,
                    })
                    to_backfill_docs.append((existing_doc, cover_image_url, target_alt))
                    continue

                report["existing_preserved"].append({
                    "url": source_url,
                    "document_id": existing_doc.id,
                    "title": existing_doc.title,
                    "action": "preserved_existing_user_edits",
                })
                continue

            # Determine Document ID
            # Legacy crawler runs emitted sequential integer counters (1, 2, 3...) as 'id'.
            # Treat numeric-only IDs as non-UUID counters and derive a stable UUIDv5 from source_url.
            raw_item_id = item.get("id")
            item_id_str = str(raw_item_id).strip() if raw_item_id is not None else ""
            if item_id_str and not item_id_str.isdigit():
                if item_id_str in existing_docs_by_id:
                    existing_by_id = existing_docs_by_id[item_id_str]
                    if existing_by_id.source_url != source_url:
                        report["conflicts_with_db"].append({
                            "index": idx,
                            "id": item_id_str,
                            "url": source_url,
                            "conflict_with_doc_url": existing_by_id.source_url,
                            "reason": "ID collision with different source_url in database",
                        })
                        continue
                    else:
                        report["existing_preserved"].append({
                            "url": source_url,
                            "document_id": item_id_str,
                            "title": existing_by_id.title,
                            "action": "preserved_existing_user_edits",
                        })
                        continue
                doc_id = item_id_str
            else:
                doc_id = generate_doc_uuid_from_url(source_url)

            # Check if derived doc_id already in DB
            if doc_id in existing_docs_by_id:
                existing_by_id = existing_docs_by_id[doc_id]
                report["conflicts_with_db"].append({
                    "index": idx,
                    "id": doc_id,
                    "url": source_url,
                    "conflict_with_doc_url": existing_by_id.source_url,
                    "reason": "Generated UUID collision with existing document",
                })
                continue

            # Category resolution
            cat_slug = (item.get("category_slug") or "general-knowledge").strip().lower()
            cat_name = item.get("category_name", cat_slug.replace("-", " ").title())
            if cat_slug not in categories_by_slug:
                if not self.dry_run:
                    new_cat = Category(name=cat_name, slug=cat_slug, description=f"Imported category: {cat_name}")
                    self.db.add(new_cat)
                    self.db.flush()
                    categories_by_slug[cat_slug] = new_cat
                else:
                    new_cat = Category(name=cat_name, slug=cat_slug, id=str(uuid.uuid4()))
                    categories_by_slug[cat_slug] = new_cat

            category = categories_by_slug[cat_slug]

            # Tags resolution
            tag_slugs = []
            for raw_t in item.get("tags", []):
                t_slug = str(raw_t).strip().lower().replace(" ", "-")
                if not t_slug:
                    continue
                tag_slugs.append(t_slug)
                if t_slug not in tags_by_slug:
                    if not self.dry_run:
                        new_t = Tag(name=t_slug.replace("-", " ").title(), slug=t_slug)
                        self.db.add(new_t)
                        self.db.flush()
                        tags_by_slug[t_slug] = new_t
                    else:
                        new_t = Tag(name=t_slug.replace("-", " ").title(), slug=t_slug, id=str(uuid.uuid4()))
                        tags_by_slug[t_slug] = new_t

            status = item.get("status", "published")
            created_at = now
            if item.get("created_at"):
                try:
                    created_at = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
                except Exception:
                    created_at = now

            published_at = created_at if status == "published" else None

            doc_entry = {
                "id": doc_id,
                "title": title,
                "summary": summary,
                "content": content,
                "category_id": category.id,
                "author": author,
                "created_by": admin_id,
                "created_at": created_at,
                "published_at": published_at,
                "status": status,
                "source_url": source_url,
                "source_license": source_license,
                "source_attribution": source_attrib,
                "cover_image_url": cover_image_url,
                "cover_image_alt": cover_image_alt,
                "seo_title": item.get("seo_title"),
                "seo_description": item.get("seo_description"),
                "seo_keywords": item.get("seo_keywords"),
                "tag_slugs": tag_slugs,
            }
            report["to_insert"].append({"id": doc_id, "url": source_url, "title": title})
            to_create_docs.append(doc_entry)

        # Apply insertions and/or cover image backfills if NOT dry run
        if not self.dry_run and (to_create_docs or to_backfill_docs):
            for d_info in to_create_docs:
                doc = Document(
                    id=d_info["id"],
                    title=d_info["title"],
                    summary=d_info["summary"],
                    content=d_info["content"],
                    category_id=d_info["category_id"],
                    author=d_info["author"],
                    created_by=d_info["created_by"],
                    created_at=d_info["created_at"],
                    published_at=d_info["published_at"],
                    status=d_info["status"],
                    source_url=d_info["source_url"],
                    source_license=d_info["source_license"],
                    source_attribution=d_info["source_attribution"],
                    cover_image_url=d_info["cover_image_url"],
                    cover_image_alt=d_info["cover_image_alt"],
                    seo_title=d_info["seo_title"],
                    seo_description=d_info["seo_description"],
                    seo_keywords=d_info["seo_keywords"],
                )
                self.db.add(doc)
                self.db.flush()

                for t_slug in d_info["tag_slugs"]:
                    tag_obj = tags_by_slug.get(t_slug)
                    if tag_obj:
                        self.db.add(DocumentTag(document_id=doc.id, tag_id=tag_obj.id))

                self.db.flush()
                self.db.expire(doc, ["document_tags"])

                # Emit revision and outbox index job in same transaction
                record_revision_and_outbox_job(self.db, doc)
                existing_docs_by_url[d_info["source_url"]] = doc
                existing_docs_by_id[doc.id] = doc

            for existing_doc, new_cover_url, new_cover_alt in to_backfill_docs:
                existing_doc.cover_image_url = new_cover_url
                existing_doc.cover_image_alt = new_cover_alt
                self.db.flush()
                record_revision_and_outbox_job(self.db, existing_doc)

            self.db.commit()

        report["inserted_count"] = len(to_create_docs) if not self.dry_run else 0
        report["preserved_count"] = len(report["existing_preserved"])
        report["would_update_count"] = len(to_backfill_docs)
        report["updated_count"] = len(to_backfill_docs) if not self.dry_run else 0
        report["skipped_count"] = (
            len(report["backfill_skipped"]) if backfill_images else len(report["existing_preserved"])
        )
        return report
