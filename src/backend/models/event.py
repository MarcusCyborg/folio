import uuid
from datetime import datetime
from typing import Optional, Any
from sqlalchemy import String, Text, DateTime, ForeignKey, UniqueConstraint, Index, JSON, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.backend.models.base import Base, utcnow

def gen_uuid() -> str:
    return str(uuid.uuid4())

class InteractionLog(Base):
    __tablename__ = "interaction_logs"
    __table_args__ = (
        Index("ix_interaction_logs_type_timestamp", "event_type", "timestamp"),
        Index("ix_interaction_logs_search_event_id", "search_event_id"),
        Index("ix_interaction_logs_clicked_doc_id", "clicked_doc_id"),
        Index(
            "ix_interaction_logs_actor_request_unique",
            "actor_key",
            "request_key",
            unique=True,
            postgresql_where=text("request_key IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)  # search | click
    user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    query_string: Mapped[str] = mapped_column(Text, nullable=False, default="")
    clicked_doc_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    search_event_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("interaction_logs.id", ondelete="SET NULL"), nullable=True)
    actor_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    result_doc_ids: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)

    user: Mapped[Optional["User"]] = relationship("User")
    clicked_document: Mapped[Optional["Document"]] = relationship("Document")

class ViewEvent(Base):
    __tablename__ = "view_events"
    __table_args__ = (
        UniqueConstraint("actor_key", "document_id", "navigation_id", name="uq_view_events_actor_doc_nav"),
        Index("ix_view_events_doc_timestamp", "document_id", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_key: Mapped[str] = mapped_column(String(64), nullable=False)
    navigation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    document: Mapped["Document"] = relationship("Document")
    user: Mapped[Optional["User"]] = relationship("User")
