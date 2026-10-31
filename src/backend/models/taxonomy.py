import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Text, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.backend.models.base import Base, utcnow

def gen_uuid() -> str:
    return str(uuid.uuid4())

class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        Index("ix_categories_slug", "slug", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    documents: Mapped[List["Document"]] = relationship("Document", back_populates="category")

class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        Index("ix_tags_slug", "slug", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)

    document_tags: Mapped[List["DocumentTag"]] = relationship("DocumentTag", back_populates="tag", cascade="all, delete-orphan")
