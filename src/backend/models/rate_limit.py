from datetime import datetime
from typing import List, Any
from sqlalchemy import String, DateTime, Index, JSON, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from src.backend.models.base import Base, utcnow

class RateLimitBucket(Base):
    """
    Persistent rate limit bucket for distributed multi-process rate limiting.
    Stores timestamps of sliding window hits and metadata for atomic row-level locking.
    """
    __tablename__ = "rate_limit_buckets"
    __table_args__ = (
        Index("ix_rate_limit_buckets_action_updated", "action", "updated_at"),
        Index("ix_rate_limit_buckets_updated_at", "updated_at"),
    )

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[List[float]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=func.clock_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=func.clock_timestamp(),
        onupdate=utcnow,
        nullable=False,
    )
