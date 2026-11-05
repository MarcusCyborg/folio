from datetime import datetime, timezone
import pytest
from sqlalchemy.orm import Session

from src.backend.models.document import Document
from src.backend.search_index.live_guard import filter_live_published_ids, verify_candidate_is_live


def test_draft_and_deleted_protection_during_index_lag(db_session: Session):
    """
    Contract Requirement 5 & Section 2.3:
    Simulates index lag:
    Index contains candidate IDs [D1, D2, D3, D4, D5].
    In PostgreSQL:
      - D2 is unpublished (status='draft')
      - D4 is soft-deleted (deleted_at IS NOT NULL)
      - D1, D3, D5 are published and active
    Live guard MUST return strictly [D1, D3, D5] in exact order with 0 seconds lag.
    Zero drafts, zero soft-deleted documents leak to live users!
    """
    published_docs = (
        db_session.query(Document)
        .filter(Document.status == "published", Document.deleted_at.is_(None))
        .limit(5)
        .all()
    )
    assert len(published_docs) >= 5

    d1, d2, d3, d4, d5 = published_docs[:5]

    # Simulate mid-session unpublication and soft-deletion in DB without updating the stale index
    d2.status = "draft"
    d4.deleted_at = datetime.now(timezone.utc)
    db_session.commit()

    candidate_ids = [d1.id, d2.id, d3.id, d4.id, d5.id]

    # Live filter on the read path
    live_ids = filter_live_published_ids(db_session, candidate_ids)

    # Invariants:
    # 1. D2 (draft) and D4 (deleted) are pruned immediately
    assert d2.id not in live_ids
    assert d4.id not in live_ids

    # 2. D1, D3, D5 are preserved in exact original candidate order
    assert live_ids == [d1.id, d3.id, d5.id]

    # 3. Individual candidate checks
    assert verify_candidate_is_live(db_session, d1.id) is True
    assert verify_candidate_is_live(db_session, d2.id) is False
    assert verify_candidate_is_live(db_session, d4.id) is False


def test_prune_without_backfill_contract_semantics(db_session: Session):
    """
    Search Contract Section 2.3 (Policy: Prune without backfill):
    If 1 out of 20 candidates on a page is pruned due to unpublication,
    the live filter returns 19 items. Candidates from the next rank window
    are NOT backfilled into this page slice.
    """
    docs = (
        db_session.query(Document)
        .filter(Document.status == "published", Document.deleted_at.is_(None))
        .limit(20)
        .all()
    )
    assert len(docs) == 20

    # Unpublish the 10th document
    target_unpub = docs[9]
    target_unpub.status = "draft"
    db_session.commit()

    page_candidate_ids = [d.id for d in docs]
    live_page_ids = filter_live_published_ids(db_session, page_candidate_ids)

    # Returns exactly 19 items (no backfill from rank 21)
    assert len(live_page_ids) == 19
    assert target_unpub.id not in live_page_ids
