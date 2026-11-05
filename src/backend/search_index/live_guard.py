from typing import List
from sqlalchemy.orm import Session
from src.backend.models.document import Document


def filter_live_published_ids(db: Session, candidate_ids: List[str]) -> List[str]:
    """
    Guarantees 0-second unpublication and soft-deletion leak protection on the read path
    even when index generations or outbox workers lag behind PostgreSQL mutations.

    Given a list of candidate document IDs (from an inverted index, snapshot context, or vector DB),
    queries PostgreSQL live state and returns only IDs that are currently:
      - status == 'published'
      - deleted_at IS NULL

    Preserves the exact relative candidate ranking order.
    Does NOT backfill pruned candidates (per Search Contract Section 2.3).
    """
    if not candidate_ids:
        return []

    # Query only published, non-deleted documents in the candidate slice
    live_rows = (
        db.query(Document.id)
        .filter(
            Document.id.in_(candidate_ids),
            Document.status == "published",
            Document.deleted_at.is_(None),
        )
        .all()
    )
    live_set = {row[0] for row in live_rows}

    # Filter while strictly preserving original candidate rank order
    return [doc_id for doc_id in candidate_ids if doc_id in live_set]


def verify_candidate_is_live(db: Session, doc_id: str) -> bool:
    """Fast check whether a single candidate document is currently published and not soft-deleted."""
    exists = (
        db.query(Document.id)
        .filter(
            Document.id == doc_id,
            Document.status == "published",
            Document.deleted_at.is_(None),
        )
        .first()
    )
    return exists is not None
