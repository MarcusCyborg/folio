import pytest
from sqlalchemy.orm import Session
from src.backend.models.document import Document, DocumentTag
from src.backend.models.taxonomy import Category, Tag
from src.backend.models.auth import User
from src.backend.models.search_index import DocumentRevision, IndexJob
from src.backend.schemas.admin import DocumentWrite, CategoryUpdate, TagUpdate, SEOMetadataUpdate
from src.backend.services.admin.content_service import (
    admin_create_document,
    admin_update_document,
    admin_update_document_status,
    admin_delete_document,
    admin_update_category,
    admin_update_tag,
)
from src.backend.services.admin.analytics_service import admin_update_document_seo


@pytest.fixture
def admin_user(db_session: Session) -> User:
    return db_session.query(User).filter(User.role_key == "super_admin").first()


@pytest.fixture
def test_category(db_session: Session) -> Category:
    return db_session.query(Category).first()


def test_outbox_job_created_same_transaction_on_document_create(
    db_session: Session,
    admin_user: User,
    test_category: Category,
):
    doc_data = DocumentWrite(
        title="Transaction Outbox Create Test",
        content="Testing transactional outbox on creation.",
        summary="Creation summary.",
        category_id=test_category.id,
    )

    doc_dict = admin_create_document(db_session, doc_data, admin_user)
    doc_id = doc_dict["id"]

    # Invariant: A DocumentRevision and IndexJob exist in the same transaction
    rev = db_session.query(DocumentRevision).filter(DocumentRevision.document_id == doc_id).first()
    assert rev is not None
    assert rev.revision_num == 1
    assert rev.status == "draft"

    job = db_session.query(IndexJob).filter(IndexJob.document_id == doc_id).first()
    assert job is not None
    assert job.operation == "delete"  # draft document starts as unindexed/delete
    assert job.state == "pending"
    assert job.revision_hash == rev.content_hash


def test_outbox_job_created_on_publish_and_unpublish(
    db_session: Session,
    admin_user: User,
    test_category: Category,
):
    doc_data = DocumentWrite(
        title="Publish Unpublish Test",
        content="Testing publish and unpublish operations.",
        summary="Summary text.",
        category_id=test_category.id,
    )
    doc_dict = admin_create_document(db_session, doc_data, admin_user)
    doc_id = doc_dict["id"]

    # 1. Publish document -> operation="upsert"
    admin_update_document_status(db_session, doc_id, "published", admin_user)
    jobs = (
        db_session.query(IndexJob)
        .filter(IndexJob.document_id == doc_id)
        .order_by(IndexJob.created_at.asc())
        .all()
    )
    assert len(jobs) == 2
    assert jobs[1].operation == "upsert"
    assert jobs[1].state == "pending"

    # 2. Unpublish document back to draft -> operation="delete"
    admin_update_document_status(db_session, doc_id, "draft", admin_user)
    jobs_after = (
        db_session.query(IndexJob)
        .filter(IndexJob.document_id == doc_id)
        .order_by(IndexJob.created_at.asc())
        .all()
    )
    assert len(jobs_after) == 3
    assert jobs_after[2].operation == "delete"


def test_outbox_job_created_on_soft_delete(
    db_session: Session,
    admin_user: User,
    test_category: Category,
):
    doc_data = DocumentWrite(
        title="Soft Delete Outbox Test",
        content="Document to be soft deleted.",
        summary="Summary.",
        category_id=test_category.id,
    )
    doc_dict = admin_create_document(db_session, doc_data, admin_user)
    doc_id = doc_dict["id"]
    admin_update_document_status(db_session, doc_id, "published", admin_user)

    admin_delete_document(db_session, doc_id, admin_user)

    latest_job = (
        db_session.query(IndexJob)
        .filter(IndexJob.document_id == doc_id)
        .order_by(IndexJob.created_at.desc())
        .first()
    )
    assert latest_job is not None
    assert latest_job.operation == "delete"


def test_outbox_job_created_on_seo_update(
    db_session: Session,
    admin_user: User,
    test_category: Category,
):
    doc_data = DocumentWrite(
        title="SEO Update Outbox Test",
        content="Testing SEO metadata update outbox trigger.",
        summary="Summary.",
        category_id=test_category.id,
    )
    doc_dict = admin_create_document(db_session, doc_data, admin_user)
    doc_id = doc_dict["id"]
    admin_update_document_status(db_session, doc_id, "published", admin_user)

    initial_job_count = db_session.query(IndexJob).filter(IndexJob.document_id == doc_id).count()

    admin_update_document_seo(
        db_session,
        doc_id,
        SEOMetadataUpdate(seo_title="New SEO Title", seo_description="New SEO Description"),
        admin_user,
    )

    new_jobs = (
        db_session.query(IndexJob)
        .filter(IndexJob.document_id == doc_id)
        .order_by(IndexJob.created_at.desc())
        .all()
    )
    assert len(new_jobs) == initial_job_count + 1
    assert new_jobs[0].operation == "upsert"


def test_taxonomy_category_update_emits_reindex_jobs(
    db_session: Session,
    admin_user: User,
    test_category: Category,
):
    # Count published documents in test_category
    docs_in_cat = (
        db_session.query(Document)
        .filter(
            Document.category_id == test_category.id,
            Document.status == "published",
            Document.deleted_at.is_(None),
        )
        .all()
    )
    assert len(docs_in_cat) > 0

    initial_job_count = db_session.query(IndexJob).count()

    # Update category name
    admin_update_category(
        db_session,
        test_category.id,
        CategoryUpdate(name="Updated Category Name"),
        admin_user,
    )

    final_job_count = db_session.query(IndexJob).count()
    assert final_job_count == initial_job_count + len(docs_in_cat)
