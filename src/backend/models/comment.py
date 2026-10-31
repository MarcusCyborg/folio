import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Text, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.backend.models.base import Base, utcnow

def gen_uuid() -> str:
    return str(uuid.uuid4())

class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (
        Index("ix_comments_document_status_created", "document_id", "status", "created_at"),
        Index("ix_comments_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="visible", nullable=False)  # visible | hidden | spam | deleted
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    document: Mapped["Document"] = relationship("Document", back_populates="comments")
    author: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    mentions: Mapped[List["CommentMention"]] = relationship("CommentMention", back_populates="comment", cascade="all, delete-orphan")
    reports: Mapped[List["Report"]] = relationship("Report", back_populates="comment", cascade="all, delete-orphan")

class CommentMention(Base):
    __tablename__ = "comment_mentions"
    __table_args__ = (
        UniqueConstraint("comment_id", "mentioned_user_id", name="uq_comment_mentions_comment_user"),
        Index("ix_comment_mentions_user", "mentioned_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    comment_id: Mapped[str] = mapped_column(String(36), ForeignKey("comments.id", ondelete="CASCADE"), nullable=False)
    mentioned_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    comment: Mapped["Comment"] = relationship("Comment", back_populates="mentions")
    mentioned_user: Mapped["User"] = relationship("User", foreign_keys=[mentioned_user_id])

class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        Index("ix_reports_status_created", "status", "created_at"),
        Index("ix_reports_comment_reporter", "comment_id", "reporter_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    comment_id: Mapped[str] = mapped_column(String(36), ForeignKey("comments.id", ondelete="CASCADE"), nullable=False)
    reporter_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)  # spam | abuse | other
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)  # open | resolved | dismissed
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    handled_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    handled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    comment: Mapped["Comment"] = relationship("Comment", back_populates="reports")
    reporter: Mapped["User"] = relationship("User", foreign_keys=[reporter_id])
    handler: Mapped[Optional["User"]] = relationship("User", foreign_keys=[handled_by])
