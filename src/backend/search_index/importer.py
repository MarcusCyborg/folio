import json
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.backend.models.document import Document, DocumentTag
from src.backend.models.taxonomy import Category, Tag
from src.backend.models.auth import User
from src.backend.search_index.outbox import record_revision_and_outbox_job


def generate_doc_uuid_from_url(url: str) -> str:
    """Generates a reproducible UUIDv5 identifier derived from the canonical URL namespace."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, url.strip()))


class CorpusImporter:
    """
    Importer for legacy JSON/JSONL corpus datasets.
    Maps source URL -> Folio Document ID idempotently, validates attribution & license,
    protects against overwriting user edits, and generates duplicate/conflict reports.
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
    ) -> Dict[str, Any]:
        """
        Parses corpus file, generates duplicate and conflict reports,
        and optionally ingests new documents into PostgreSQL.
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
        seen_ids_in_file: Dict[str, int] = {}

        report: Dict[str, Any] = {
            "file": str(file_path),
            "dry_run": self.dry_run,
            "total_scanned": len(records),
            "bad_lines": bad_lines,
            "valid_records": 0,
            "invalid_records": [],
            "duplicates_in_file": [],
            "conflicts_with_db": [],
            "existing_preserved": [],
            "to_insert": [],
            "attribution_verified": 0,
            "license_verified": 0,
            "inserted_count": 0,
            "preserved_count": 0,
        }

        now = datetime.now(timezone.utc)
        to_create_docs = []

        for idx, item in enumerate(records, start=1):
            source_url = (item.get("source_url") or item.get("url") or "").strip()
            title = (item.get("title") or "").strip()
            content = (item.get("content") or item.get("text") or "").strip()
            summary = (item.get("summary") or "").strip()

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

            if not summary:
                # Extract first non-empty paragraph or up to 400 chars as meaningful summary
                lines = [line.strip() for line in content.split("\n") if line.strip()]
                summary = lines[0][:400] if lines else title

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

            # Check if source_url already exists in PostgreSQL -> IDEMPOTENT PRESERVATION
            if source_url in existing_docs_by_url:
                existing_doc = existing_docs_by_url[source_url]
                report["existing_preserved"].append({
                    "url": source_url,
                    "document_id": existing_doc.id,
                    "title": existing_doc.title,
                    "action": "preserved_existing_user_edits",
                })
                continue

            # Determine Document ID
            item_id = item.get("id")
            if item_id:
                item_id = str(item_id).strip()
                if item_id in existing_docs_by_id:
                    existing_by_id = existing_docs_by_id[item_id]
                    if existing_by_id.source_url != source_url:
                        # Conflict: ID belongs to a different document
                        report["conflicts_with_db"].append({
                            "index": idx,
                            "id": item_id,
                            "url": source_url,
                            "conflict_with_doc_url": existing_by_id.source_url,
                            "reason": "ID collision with different source_url in database",
                        })
                        continue
                    else:
                        report["existing_preserved"].append({
                            "url": source_url,
                            "document_id": item_id,
                            "title": existing_by_id.title,
                            "action": "preserved_existing_user_edits",
                        })
                        continue
                doc_id = item_id
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
                "cover_image_url": item.get("cover_image_url"),
                "cover_image_alt": item.get("cover_image_alt"),
                "seo_title": item.get("seo_title"),
                "seo_description": item.get("seo_description"),
                "seo_keywords": item.get("seo_keywords"),
                "tag_slugs": tag_slugs,
            }
            report["to_insert"].append({"id": doc_id, "url": source_url, "title": title})
            to_create_docs.append(doc_entry)

        # Apply insertions if NOT dry run
        if not self.dry_run and to_create_docs:
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

            self.db.commit()

        report["inserted_count"] = len(to_create_docs) if not self.dry_run else 0
        report["preserved_count"] = len(report["existing_preserved"])
        return report
