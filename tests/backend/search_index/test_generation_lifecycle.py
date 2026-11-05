import uuid
from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy.orm import Session

from src.backend.models.document import Document
from src.backend.models.taxonomy import Category
from src.backend.models.search_index import (
    IndexGeneration,
    SearchContext,
    IndexJob,
)
from src.backend.search_index.manager import (
    GenerationManager,
    IndexBuildError,
    IndexVerificationError,
)
from src.backend.search_index.storage import GenerationStorage
from src.backend.schemas.admin import DocumentWrite
from src.backend.services.admin.content_service import (
    admin_create_document,
    admin_update_document_status,
)
from src.backend.models.auth import User


def test_build_verify_and_atomic_swap(db_session: Session):
    # 1. Build initial generation
    gen1 = GenerationManager.build_new_generation(db_session, force=True)
    assert gen1.status == "active"
    assert gen1.doc_count > 0

    active_now = GenerationManager.get_active_generation(db_session)
    assert active_now.id == gen1.id

    # 2. Build second generation and atomic swap
    gen2 = GenerationManager.build_new_generation(db_session, force=True)
    assert gen2.status == "active"
    assert gen2.id != gen1.id

    # Verify gen1 transitioned to draining
    db_session.refresh(gen1)
    assert gen1.status == "draining"

    # Current active is gen2
    active_now2 = GenerationManager.get_active_generation(db_session)
    assert active_now2.id == gen2.id


def test_failed_rebuild_preserves_active_generation(db_session: Session):
    # Ensure gen1 is active
    gen1 = GenerationManager.build_new_generation(db_session, force=True)
    assert gen1.status == "active"

    # Try building gen2 with simulated failure during build
    with pytest.raises(IndexBuildError):
        GenerationManager.build_new_generation(db_session, force=True, sim_fail_at="build")

    # Invariant: gen1 MUST STILL be active! No downtime, no corrupted state!
    active_now = GenerationManager.get_active_generation(db_session)
    assert active_now.id == gen1.id
    assert active_now.status == "active"

    # Try building gen3 with simulated failure during verification
    with pytest.raises(IndexVerificationError):
        GenerationManager.build_new_generation(db_session, force=True, sim_fail_at="verify")

    active_now2 = GenerationManager.get_active_generation(db_session)
    assert active_now2.id == gen1.id
    assert active_now2.status == "active"


def test_concurrent_rebuild_and_writes_not_lost(db_session: Session):
    """
    Simulates a write occurring concurrently while a rebuild is taking place.
    The rebuild mechanism must catch up pending outbox jobs created during the build,
    so that newly created/published documents are NOT lost in the new generation.
    """
    admin_user = db_session.query(User).filter(User.role_key == "super_admin").first()
    category = db_session.query(Category).first()

    # Initial active generation
    gen1 = GenerationManager.build_new_generation(db_session, force=True)
    assert gen1.status == "active"

    # Simulate creating a new document concurrently
    doc_data = DocumentWrite(
        title="Concurrent Write During Rebuild",
        content="This document was created concurrently while rebuild was running.",
        summary="Concurrent summary.",
        category_id=category.id,
    )
    doc_dict = admin_create_document(db_session, doc_data, admin_user)
    doc_id = doc_dict["id"]
    admin_update_document_status(db_session, doc_id, "published", admin_user)

    # Build new generation G2
    gen2 = GenerationManager.build_new_generation(db_session, force=True)
    assert gen2.status == "active"

    # Verify that the concurrent document IS PRESENT in the new generation!
    storage2 = GenerationStorage(gen2.id)
    manifest2 = storage2.load_manifest()
    assert doc_id in manifest2["docs"]
    assert manifest2["docs"][doc_id]["title"] == "Concurrent Write During Rebuild"


def test_search_context_lease_protects_draining_generation_from_gc(db_session: Session):
    """
    Contract Section 2.3:
    Active search context holds a lease on the referenced index generation.
    Garbage collection MUST NOT purge a draining generation while an unexpired lease exists.
    """
    gen1 = GenerationManager.build_new_generation(db_session, force=True)
    # Build gen2 so gen1 transitions to draining
    gen2 = GenerationManager.build_new_generation(db_session, force=True)

    db_session.refresh(gen1)
    assert gen1.status == "draining"

    now = datetime.now(timezone.utc)
    # Create an active SearchContext referencing gen1 with 15 minute TTL
    ctx = SearchContext(
        token=str(uuid.uuid4()),
        actor_key="test-actor-lease-guard",
        query="test lease query",
        mode="bm25",
        filters_hash="filters-hash-1",
        page_size=20,
        index_generation_id=gen1.id,
        candidate_ids=["dummy-1"],
        snapshot_candidate_count=1,
        created_at=now,
        expires_at=now + timedelta(minutes=15),
    )
    db_session.add(ctx)
    db_session.commit()

    # Attempt GC: gen1 has active lease, MUST NOT be purged!
    purged = GenerationManager.garbage_collect_generations(db_session)
    assert gen1.id not in purged

    db_session.refresh(gen1)
    assert gen1.status == "draining"

    # Now simulate context expiration
    ctx.expires_at = now - timedelta(seconds=1)
    db_session.commit()

    # Attempt GC again: lease is now expired -> gen1 is purged and archived
    purged2 = GenerationManager.garbage_collect_generations(db_session)
    assert gen1.id in purged2

    db_session.refresh(gen1)
    assert gen1.status == "archived"
