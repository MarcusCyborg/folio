import uuid
from datetime import datetime
from typing import Optional, Any
from sqlalchemy import (
    String,
    Text,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
    JSON,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.backend.models.base import Base, utcnow

def gen_uuid() -> str:
    return str(uuid.uuid4())

jsonb_type = JSON().with_variant(postgresql.JSONB, "postgresql")


class DocumentRevision(Base):
    """Immutable content revision snapshot for change tracking and stale-revision protection."""
    __tablename__ = "document_revisions"
    __table_args__ = (
        UniqueConstraint("document_id", "revision_num", name="uq_document_revisions_doc_rev"),
        Index("ix_document_revisions_document_id", "document_id"),
        Index("ix_document_revisions_doc_hash", "document_id", "content_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision_num: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    document: Mapped["Document"] = relationship("Document", foreign_keys=[document_id])


class IndexJob(Base):
    """Transactional outbox queue record for asynchronous search index synchronization."""
    __tablename__ = "index_jobs"
    __table_args__ = (
        Index("ix_index_jobs_state_scheduled", "state", "scheduled_at", "created_at"),
        Index("ix_index_jobs_doc_created", "document_id", "created_at"),
        Index("ix_index_jobs_state_locked", "state", "locked_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(30), nullable=False)  # 'upsert' | 'delete'
    state: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending | processing | completed | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    document: Mapped["Document"] = relationship("Document", foreign_keys=[document_id])


class IndexGeneration(Base):
    """Index generation metadata tracking build, verification, and atomic active generation status."""
    __tablename__ = "index_generations"
    __table_args__ = (
        UniqueConstraint("generation_num", name="uq_index_generations_num"),
        Index("ix_index_generations_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. "idx-gen-20261101-0001"
    generation_num: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="building", nullable=False)  # building | ready | active | draining | archived | failed
    doc_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    manifest: Mapped[Optional[Any]] = mapped_column(jsonb_type, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    active_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class SearchContext(Base):
    """Server-issued actor-bound search context for pagination stability and generation lease (Contract v2.1.0)."""
    __tablename__ = "search_contexts"
    __table_args__ = (
        Index("ix_search_contexts_token", "token", unique=True),
        Index("ix_search_contexts_actor_key", "actor_key"),
        Index("ix_search_contexts_expires_at", "expires_at"),
        Index("ix_search_contexts_gen_expires", "index_generation_id", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    token: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_key: Mapped[str] = mapped_column(String(64), nullable=False)
    query: Mapped[str] = mapped_column(String(200), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), default="bm25", nullable=False)
    engine_used: Mapped[str] = mapped_column(String(30), default="bm25", nullable=False)
    is_degraded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    degraded_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    filters_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    page_size: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    index_generation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("index_generations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    candidate_ids: Mapped[Any] = mapped_column(jsonb_type, nullable=False)  # List[str] of canonical UUIDs
    candidate_scores: Mapped[Optional[Any]] = mapped_column(jsonb_type, nullable=True)  # Optional[List[float]]
    snapshot_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    snapshot_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    is_approximate_total: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    generation: Mapped["IndexGeneration"] = relationship("IndexGeneration", foreign_keys=[index_generation_id])
