"""Portable BM25 generations for runtimes without a persistent filesystem."""

import base64
import gzip
import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import func, text
from sqlalchemy.orm import selectinload

from src.backend.models.document import Document
from src.backend.models.search_index import IndexGeneration
from src.backend.search.analyzer import ANALYZER_VERSION
from src.backend.search.builder import IndexBuilder
from src.backend.search.index import InvertedIndex, DocumentMetadata


def source_signature(db):
    # Hash only indexed fields: page views must not trigger an index rebuild.
    rows = db.execute(text("""
        SELECT d.id, md5(jsonb_build_array(
            d.title, d.summary, d.content, d.category_id, d.created_at,
            ARRAY(SELECT dt.tag_id FROM document_tags dt
                  WHERE dt.document_id = d.id ORDER BY dt.tag_id)
        )::text)
        FROM documents d
        WHERE d.status = 'published' AND d.deleted_at IS NULL
        ORDER BY d.id
    """)).all()
    return hashlib.sha256(json.dumps(
        [ANALYZER_VERSION, [list(row) for row in rows]],
        separators=(",", ":"),
    ).encode()).hexdigest()


def pack_index(index):
    payload = {
        "generation_id": index.generation_id,
        "analyzer_version": index.analyzer_version,
        "documents": {key: asdict(value) for key, value in index.documents.items()},
        "postings": index.postings,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {
        "storage_backend": "database",
        "format_version": 1,
        "checksum": hashlib.sha256(raw).hexdigest(),
        "payload": base64.b64encode(gzip.compress(raw, mtime=0)).decode("ascii"),
        "doc_count": index.total_docs,
    }


@lru_cache(maxsize=4)
def _unpack_index(generation_id, checksum, payload):
    raw = gzip.decompress(base64.b64decode(payload, validate=True))
    if hashlib.sha256(raw).hexdigest() != checksum:
        raise ValueError("Database index checksum mismatch")
    data = json.loads(raw)
    if data["generation_id"] != generation_id or data["analyzer_version"] != ANALYZER_VERSION:
        raise ValueError("Database index generation or analyzer mismatch")
    index = InvertedIndex(generation_id=generation_id)
    index.documents = {key: DocumentMetadata(**value) for key, value in data["documents"].items()}
    index.postings = data["postings"]
    index.df = {term: len(postings) for term, postings in index.postings.items()}
    index._recalculate_corpus_stats()
    index.checksum = checksum
    return index


def load_index(generation):
    manifest = generation.manifest or {}
    if manifest.get("storage_backend") != "database" or manifest.get("format_version") != 1:
        raise ValueError("Database index payload unavailable")
    return _unpack_index(generation.id, manifest["checksum"], manifest["payload"])


def ensure_database_generation(db, force=False):
    """Load or atomically rebuild a shared generation; old search contexts stay valid."""
    from src.backend.search_index.manager import GenerationManager

    db.flush()

    def current():
        generation = GenerationManager.get_active_generation(db)
        signature = source_signature(db)
        if generation and (generation.manifest or {}).get("source_signature") == signature:
            try:
                return generation, load_index(generation), signature
            except (ValueError, KeyError, OSError, EOFError):
                pass
        return generation, None, signature

    generation, index, signature = current()
    if index is not None and not force:
        return generation, index

    # Serialize cold starts across serverless instances, then recheck after waiting.
    db.execute(text("SELECT pg_advisory_xact_lock(681472903)"))
    db.expire_all()
    generation, index, signature = current()
    if index is not None and not force:
        db.commit()
        return generation, index

    # Keep the fingerprint and document snapshot consistent during publication/tag edits.
    db.execute(text("LOCK TABLE documents, document_tags IN SHARE MODE"))
    signature = source_signature(db)
    docs = db.query(Document).options(selectinload(Document.document_tags)).filter(
        Document.status == "published", Document.deleted_at.is_(None),
    ).populate_existing().all()
    generation_id = f"idx-db-{uuid.uuid4().hex}"
    index = IndexBuilder().build_from_documents(docs, generation_id)
    manifest = pack_index(index)
    manifest["source_signature"] = signature
    now = datetime.now(timezone.utc)
    next_num = (db.query(func.max(IndexGeneration.generation_num)).scalar() or 0) + 1
    db.query(IndexGeneration).filter(IndexGeneration.status == "active").update(
        {"status": "draining", "updated_at": now}, synchronize_session=False,
    )
    generation = IndexGeneration(
        id=generation_id, generation_num=next_num, status="active",
        doc_count=index.total_docs, manifest=manifest, active_at=now,
    )
    db.add(generation)
    db.commit()
    return generation, index
