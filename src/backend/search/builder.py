"""
Folio Inverted Index Builder.

Constructs, updates, and persists inverted indexes from PostgreSQL documents or memory objects.
Handles combining document fields (title, summary, content), extracting taxonomy metadata,
and writing posting lists to generation storage directories.
"""

from pathlib import Path
from typing import Iterable, List, Optional, Any
from sqlalchemy.orm import Session

from src.backend.models.document import Document
from src.backend.search.analyzer import TextAnalyzer, default_analyzer
from src.backend.search.index import InvertedIndex


class IndexBuilder:
    """
    Builder responsible for generating and updating InvertedIndex instances
    for specific index generations.
    """

    def __init__(
        self,
        analyzer: Optional[TextAnalyzer] = None,
    ):
        self.analyzer = analyzer or default_analyzer

    def build_from_documents(
        self,
        documents: Iterable[Any],
        generation_id: str,
        output_dir: Optional[Path] = None,
    ) -> InvertedIndex:
        """
        Builds an InvertedIndex from an iterable of Document objects (or dicts).
        Indexes title, summary, and content.
        Preserves category_id, tag_ids, created_at, status, and title metadata.
        Optionally saves to output_dir if provided.
        """
        index = InvertedIndex(generation_id=generation_id, analyzer=self.analyzer)

        for doc in documents:
            if isinstance(doc, dict):
                doc_id = doc["id"]
                title = doc.get("title", "")
                summary = doc.get("summary", "")
                content = doc.get("content", "")
                category_id = doc.get("category_id")
                tag_ids = doc.get("tag_ids", [])
                created_at = doc.get("created_at")
                status = doc.get("status", "published")
            else:
                doc_id = doc.id
                title = doc.title or ""
                summary = doc.summary or ""
                content = doc.content or ""
                category_id = doc.category_id
                tag_ids = [dt.tag_id for dt in doc.document_tags] if hasattr(doc, "document_tags") and doc.document_tags else []
                created_at = doc.created_at.isoformat() if hasattr(doc, "created_at") and doc.created_at else None
                status = doc.status or "published"

            # Combine fields: title + summary + content
            combined_text = f"{title} {summary} {content}".strip()

            index.upsert_document(
                doc_id=doc_id,
                text=combined_text,
                title=title,
                category_id=category_id,
                tag_ids=tag_ids,
                created_at=created_at,
                status=status,
            )

        if output_dir:
            index.save(output_dir)

        return index

    def build_from_db(
        self,
        db: Session,
        generation_id: str,
        output_dir: Optional[Path] = None,
    ) -> InvertedIndex:
        """
        Queries all published, non-deleted documents in PostgreSQL and builds
        the inverted index for generation_id.
        """
        docs = (
            db.query(Document)
            .filter(
                Document.status == "published",
                Document.deleted_at.is_(None),
            )
            .all()
        )
        return self.build_from_documents(docs, generation_id=generation_id, output_dir=output_dir)
