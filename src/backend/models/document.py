import uuid
from datetime import datetime
from typing import Optional, List, Any
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, UniqueConstraint, Index, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.backend.models.base import Base, utcnow

def gen_uuid() -> str:
    return str(uuid.uuid4())

class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_status_deleted_created_id", "status", "deleted_at", "created_at", "id"),
        Index("ix_documents_category_id", "category_id"),
        Index("ix_documents_source_url", "source_url", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[str] = mapped_column(String(36), ForeignKey("categories.id"), nullable=False)
    author: Mapped[str] = mapped_column(String(100), nullable=False, default="Wikipedia contributors")
    created_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    views_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)  # draft | published
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    source_license: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_attribution: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    cover_image_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    cover_image_alt: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    seo_title: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    seo_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    seo_keywords: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)

    category: Mapped["Category"] = relationship("Category", back_populates="documents")
    creator: Mapped[Optional["User"]] = relationship("User", foreign_keys=[created_by])
    document_tags: Mapped[List["DocumentTag"]] = relationship("DocumentTag", back_populates="document", cascade="all, delete-orphan")
    likes: Mapped[List["DocumentLike"]] = relationship("DocumentLike", back_populates="document", cascade="all, delete-orphan")
    comments: Mapped[List["Comment"]] = relationship("Comment", back_populates="document", cascade="all, delete-orphan")

class DocumentTag(Base):
    __tablename__ = "document_tags"
    __table_args__ = (
        UniqueConstraint("document_id", "tag_id", name="uq_document_tags_doc_tag"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    tag_id: Mapped[str] = mapped_column(String(36), ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)

    document: Mapped["Document"] = relationship("Document", back_populates="document_tags")
    tag: Mapped["Tag"] = relationship("Tag", back_populates="document_tags")

class DocumentLike(Base):
    __tablename__ = "document_likes"
    __table_args__ = (
        UniqueConstraint("document_id", "user_id", name="uq_document_likes_doc_user"),
        Index("ix_document_likes_document_id", "document_id"),
        Index("ix_document_likes_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    document: Mapped["Document"] = relationship("Document", back_populates="likes")
    user: Mapped["User"] = relationship("User")
