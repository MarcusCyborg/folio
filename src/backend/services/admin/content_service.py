import re
from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from src.backend.models.document import Document, DocumentTag
from src.backend.models.taxonomy import Category, Tag
from src.backend.models.auth import User
from src.backend.core.audit import write_audit
from src.backend.core.exceptions import AppException
from src.backend.core.sanitizer import render_and_sanitize_markdown
from src.backend.core.wiki_content import clean_wikipedia_content
from src.backend.schemas.library import Taxon
from src.backend.schemas.admin import DocumentWrite, CategoryWrite, TagWrite, CategoryUpdate, TagUpdate
from src.backend.search_index.outbox import (
    record_revision_and_outbox_job,
    emit_taxonomy_reindex_jobs,
)

def slugify(text: str) -> str:
    if not text:
        return ""
    s = re.sub(r'[^a-zA-Z0-9\s-]', '', text).strip().lower()
    return re.sub(r'[\s-]+', '-', s)

def admin_list_documents(
    db: Session,
    q: Optional[str] = None,
    status_filter: Optional[str] = None,
    category_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[dict], int]:
    query = db.query(Document).filter(Document.deleted_at.is_(None))

    if q and q.strip():
        escaped = q.strip().replace('%', '\\%').replace('_', '\\_')
        safe_q = f"%{escaped}%"
        query = query.filter(Document.title.ilike(safe_q) | Document.summary.ilike(safe_q))

    if status_filter:
        query = query.filter(Document.status == status_filter)

    if category_id:
        query = query.filter(Document.category_id == category_id)

    total = query.count()
    docs = query.order_by(Document.created_at.desc(), Document.id.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for d in docs:
        tags_list = [Taxon(id=dt.tag.id, name=dt.tag.name, slug=dt.tag.slug) for dt in d.document_tags]
        items.append({
            "id": d.id,
            "title": d.title,
            "summary": d.summary,
            "author": d.author,
            "status": d.status,
            "created_by": d.created_by,
            "created_at": d.created_at,
            "updated_at": d.updated_at,
            "published_at": d.published_at,
            "views_count": d.views_count,
            "likes_count": len(d.likes),
            "comments_count": len(d.comments),
            "category": Taxon(id=d.category.id, name=d.category.name, slug=d.category.slug),
            "category_id": d.category_id,
            "tags": tags_list,
            "cover_image_url": d.cover_image_url,
            "cover_image_alt": d.cover_image_alt,
            "source_url": d.source_url,
            "deleted_at": d.deleted_at,
        })
    return items, total

def admin_get_document(db: Session, doc_id: str) -> dict:
    doc = db.query(Document).filter(Document.id == doc_id, Document.deleted_at.is_(None)).first()
    if not doc:
        raise AppException(status_code=404, code="DOCUMENT_NOT_FOUND", message="Document not found")

    tags_list = [Taxon(id=dt.tag.id, name=dt.tag.name, slug=dt.tag.slug) for dt in doc.document_tags]
    content = clean_wikipedia_content(doc.content, doc.source_url)
    return {
        "id": doc.id,
        "title": doc.title,
        "summary": doc.summary,
        "content": content,
        "rendered_content": render_and_sanitize_markdown(content),
        "author": doc.author,
        "status": doc.status,
        "created_by": doc.created_by,
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
        "published_at": doc.published_at,
        "views_count": doc.views_count,
        "likes_count": len(doc.likes),
        "comments_count": len(doc.comments),
        "category": Taxon(id=doc.category.id, name=doc.category.name, slug=doc.category.slug),
        "category_id": doc.category_id,
        "tags": tags_list,
        "cover_image_url": doc.cover_image_url,
        "cover_image_alt": doc.cover_image_alt,
        "source_url": doc.source_url,
        "source_license": doc.source_license,
        "source_attribution": doc.source_attribution,
        "seo_title": doc.seo_title,
        "seo_description": doc.seo_description,
        "seo_keywords": doc.seo_keywords,
        "deleted_at": doc.deleted_at,
        "liked_by_me": False,
    }

def admin_create_document(db: Session, data: DocumentWrite, user: User) -> dict:
    cat = db.query(Category).filter(Category.id == data.category_id).first()
    if not cat:
        raise AppException(status_code=422, code="INVALID_CATEGORY", message="Category does not exist")

    # Author defaults to current user's display_name if empty
    author_name = data.author.strip() if data.author and data.author.strip() else user.display_name

    # Validate tag_ids before any mutation
    requested_tag_ids = []
    if data.tag_ids:
        requested_tag_ids = list(dict.fromkeys(data.tag_ids))
        valid_tags = db.query(Tag).filter(Tag.id.in_(requested_tag_ids)).all()
        found_ids = {t.id for t in valid_tags}
        missing_ids = [tid for tid in requested_tag_ids if tid not in found_ids]
        if missing_ids:
            raise AppException(
                status_code=422,
                code="INVALID_TAG_IDS",
                message=f"The following tag IDs do not exist: {', '.join(missing_ids)}",
                details={"missing_tag_ids": missing_ids}
            )

    # Pre-check source_url uniqueness if provided
    clean_source_url = data.source_url.strip() if data.source_url and data.source_url.strip() else None
    if clean_source_url:
        existing_doc = db.query(Document).filter(
            Document.source_url == clean_source_url,
            Document.deleted_at.is_(None)
        ).first()
        if existing_doc:
            raise AppException(
                status_code=409,
                code="SOURCE_URL_CONFLICT",
                message="A document with this source URL already exists",
                details={"field": "source_url"}
            )

    doc = Document(
        title=data.title.strip(),
        content=data.content,
        summary=data.summary.strip(),
        category_id=cat.id,
        author=author_name,
        created_by=user.id,
        status="draft",  # Always draft on create
        published_at=None,
        cover_image_url=data.cover_image_url.strip() if data.cover_image_url and data.cover_image_url.strip() else None,
        cover_image_alt=data.cover_image_alt.strip() if data.cover_image_alt and data.cover_image_alt.strip() else None,
        source_url=clean_source_url,
        source_license=data.source_license.strip() if data.source_license and data.source_license.strip() else None,
        source_attribution=data.source_attribution.strip() if data.source_attribution and data.source_attribution.strip() else None,
    )
    db.add(doc)
    try:
        db.flush()
    except IntegrityError as err:
        db.rollback()
        err_msg = str(err).lower()
        if "source_url" in err_msg or "ix_documents_source_url" in err_msg:
            raise AppException(
                status_code=409,
                code="SOURCE_URL_CONFLICT",
                message="A document with this source URL already exists",
                details={"field": "source_url"}
            )
        raise

    # Attach tags
    for tid in requested_tag_ids:
        db.add(DocumentTag(document_id=doc.id, tag_id=tid))
    db.flush()
    db.expire(doc, ["document_tags", "category"])

    write_audit(
        db,
        actor=user,
        action="document.create",
        entity_type="document",
        entity_id=doc.id,
        after={"title": doc.title, "status": doc.status}
    )
    record_revision_and_outbox_job(db, doc)
    db.commit()
    db.refresh(doc)
    db.expire(doc, ["document_tags", "category"])
    return admin_get_document(db, doc.id)

def admin_update_document(db: Session, doc_id: str, data: dict, user: User) -> dict:
    doc = db.query(Document).filter(Document.id == doc_id, Document.deleted_at.is_(None)).first()
    if not doc:
        raise AppException(status_code=404, code="DOCUMENT_NOT_FOUND", message="Document not found")

    before_state = {"title": doc.title, "summary": doc.summary}

    # 1. Validate tag_ids before any mutation if provided
    requested_tag_ids = None
    if "tag_ids" in data and data["tag_ids"] is not None:
        requested_tag_ids = list(dict.fromkeys(data["tag_ids"]))
        if requested_tag_ids:
            valid_tags = db.query(Tag).filter(Tag.id.in_(requested_tag_ids)).all()
            found_ids = {t.id for t in valid_tags}
            missing_ids = [tid for tid in requested_tag_ids if tid not in found_ids]
            if missing_ids:
                raise AppException(
                    status_code=422,
                    code="INVALID_TAG_IDS",
                    message=f"The following tag IDs do not exist: {', '.join(missing_ids)}",
                    details={"missing_tag_ids": missing_ids}
                )

    # 2. Check source_url uniqueness if provided
    if "source_url" in data and data["source_url"]:
        clean_url = data["source_url"].strip() if data["source_url"].strip() else None
        if clean_url:
            existing_doc = db.query(Document).filter(
                Document.source_url == clean_url,
                Document.id != doc.id,
                Document.deleted_at.is_(None)
            ).first()
            if existing_doc:
                raise AppException(
                    status_code=409,
                    code="SOURCE_URL_CONFLICT",
                    message="A document with this source URL already exists",
                    details={"field": "source_url"}
                )

    if "title" in data and data["title"] is not None:
        title_clean = data["title"].strip()
        if not title_clean:
            raise AppException(status_code=422, code="INVALID_TITLE", message="Title cannot be whitespace only")
        doc.title = title_clean
    if "content" in data and data["content"] is not None:
        content_clean = data["content"].strip()
        if not content_clean:
            raise AppException(status_code=422, code="INVALID_CONTENT", message="Content cannot be whitespace only")
        doc.content = data["content"]
    if "summary" in data and data["summary"] is not None:
        summary_clean = data["summary"].strip()
        if not summary_clean:
            raise AppException(status_code=422, code="INVALID_SUMMARY", message="Summary cannot be whitespace only")
        doc.summary = summary_clean
    if "category_id" in data and data["category_id"] is not None:
        cat = db.query(Category).filter(Category.id == data["category_id"]).first()
        if not cat:
            raise AppException(status_code=422, code="INVALID_CATEGORY", message="Category does not exist")
        doc.category_id = cat.id
    if "author" in data:
        author_val = data["author"]
        if author_val is None or (isinstance(author_val, str) and not author_val.strip()):
            doc.author = user.display_name or "Wikipedia contributors"
        else:
            doc.author = str(author_val).strip()
    if "cover_image_url" in data:
        cov_url = data["cover_image_url"]
        doc.cover_image_url = cov_url.strip() if (cov_url and cov_url.strip()) else None
    if "cover_image_alt" in data:
        cov_alt = data["cover_image_alt"]
        doc.cover_image_alt = cov_alt.strip() if (cov_alt and cov_alt.strip()) else None
    if "source_url" in data:
        s_url = data["source_url"]
        doc.source_url = s_url.strip() if (s_url and s_url.strip()) else None
    if "source_license" in data:
        s_lic = data["source_license"]
        doc.source_license = s_lic.strip() if (s_lic and s_lic.strip()) else None
    if "source_attribution" in data:
        s_attr = data["source_attribution"]
        doc.source_attribution = s_attr.strip() if (s_attr and s_attr.strip()) else None

    # 3. Only mutate tags if tag_ids was explicitly provided in data
    if requested_tag_ids is not None:
        db.query(DocumentTag).filter(DocumentTag.document_id == doc.id).delete(synchronize_session=False)
        for tid in requested_tag_ids:
            db.add(DocumentTag(document_id=doc.id, tag_id=tid))
        db.flush()
        db.expire(doc, ["document_tags"])

    doc.updated_at = datetime.now(timezone.utc)
    try:
        db.flush()
    except IntegrityError as err:
        db.rollback()
        err_msg = str(err).lower()
        if "source_url" in err_msg or "ix_documents_source_url" in err_msg:
            raise AppException(
                status_code=409,
                code="SOURCE_URL_CONFLICT",
                message="A document with this source URL already exists",
                details={"field": "source_url"}
            )
        raise

    db.expire(doc, ["document_tags", "category"])
    write_audit(
        db,
        actor=user,
        action="document.update",
        entity_type="document",
        entity_id=doc.id,
        before=before_state,
        after={"title": doc.title, "summary": doc.summary}
    )
    record_revision_and_outbox_job(db, doc)
    db.commit()
    db.expire(doc, ["document_tags", "category"])
    return admin_get_document(db, doc.id)

def admin_update_document_status(db: Session, doc_id: str, new_status: str, user: User) -> dict:
    doc = db.query(Document).filter(Document.id == doc_id, Document.deleted_at.is_(None)).first()
    if not doc:
        raise AppException(status_code=404, code="DOCUMENT_NOT_FOUND", message="Document not found")

    if new_status == "published":
        # Validate required fields
        if (
            not doc.title or not doc.title.strip()
            or not doc.content or not doc.content.strip()
            or not doc.summary or not doc.summary.strip()
            or not doc.category_id
        ):
            raise AppException(
                status_code=422,
                code="INCOMPLETE_DOCUMENT",
                message="Cannot publish document: title, content, summary, and category are required."
            )
        if not doc.published_at:
            doc.published_at = datetime.now(timezone.utc)

    before_status = doc.status
    doc.status = new_status
    doc.updated_at = datetime.now(timezone.utc)
    db.flush()

    write_audit(
        db,
        actor=user,
        action="document.status_update",
        entity_type="document",
        entity_id=doc.id,
        before={"status": before_status},
        after={"status": doc.status}
    )
    op = "upsert" if doc.status == "published" else "delete"
    record_revision_and_outbox_job(db, doc, operation=op)
    db.commit()
    db.expire(doc, ["document_tags", "category"])
    return admin_get_document(db, doc.id)

def admin_delete_document(db: Session, doc_id: str, user: User):
    doc = db.query(Document).filter(Document.id == doc_id, Document.deleted_at.is_(None)).first()
    if not doc:
        raise AppException(status_code=404, code="DOCUMENT_NOT_FOUND", message="Document not found")

    doc.deleted_at = datetime.now(timezone.utc)
    db.flush()
    write_audit(
        db,
        actor=user,
        action="document.soft_delete",
        entity_type="document",
        entity_id=doc.id,
        before={"status": doc.status}
    )
    record_revision_and_outbox_job(db, doc, operation="delete")
    db.commit()

# --- Taxonomy CRUD ---

def admin_list_categories(db: Session, page: int = 1, page_size: int = 50) -> Tuple[List[dict], int]:
    query = (
        db.query(
            Category,
            func.count(Document.id).label("doc_count")
        )
        .outerjoin(
            Document,
            (Category.id == Document.category_id) & (Document.deleted_at.is_(None))
        )
        .group_by(Category.id)
        .order_by(Category.name.asc())
    )
    total = db.query(Category).count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    results = [
        {
            "id": cat.id,
            "name": cat.name,
            "slug": cat.slug,
            "description": cat.description,
            "document_count": count,
        }
        for cat, count in items
    ]
    return results, total

def admin_create_category(db: Session, data: CategoryWrite, user: User) -> dict:
    if not data.name.strip():
        raise AppException(status_code=422, code="INVALID_NAME", message="Category name cannot be empty")

    raw_slug = data.slug.strip() if data.slug and data.slug.strip() else data.name.strip()
    slug = slugify(raw_slug)
    if not slug:
        raise AppException(status_code=422, code="INVALID_SLUG", message="Category slug cannot be empty")

    existing = db.query(Category).filter(Category.slug == slug).first()
    if existing:
        raise AppException(status_code=409, code="SLUG_EXISTS", message="Category with this slug already exists")

    cat = Category(name=data.name.strip(), slug=slug, description=data.description)
    db.add(cat)
    db.flush()
    write_audit(db, actor=user, action="taxonomy.category_create", entity_type="category", entity_id=cat.id, after={"name": cat.name, "slug": cat.slug})
    db.commit()
    return {"id": cat.id, "name": cat.name, "slug": cat.slug, "description": cat.description}

def admin_update_category(db: Session, cat_id: str, data: CategoryUpdate, user: User) -> dict:
    cat = db.query(Category).filter(Category.id == cat_id).first()
    if not cat:
        raise AppException(status_code=404, code="CATEGORY_NOT_FOUND", message="Category not found")

    before_state = {"name": cat.name, "slug": cat.slug, "description": cat.description}

    if data.name is not None:
        name_clean = data.name.strip()
        if not name_clean:
            raise AppException(status_code=422, code="INVALID_NAME", message="Category name cannot be empty")
        cat.name = name_clean

    if "description" in data.model_fields_set:
        cat.description = data.description.strip() if (data.description and data.description.strip()) else None

    if data.slug is not None:
        slug_clean = slugify(data.slug)
        if not slug_clean:
            raise AppException(status_code=422, code="INVALID_SLUG", message="Category slug cannot be empty")
        if slug_clean != cat.slug:
            existing = db.query(Category).filter(Category.slug == slug_clean).first()
            if existing:
                raise AppException(status_code=409, code="SLUG_EXISTS", message="Category with this slug already exists")
            cat.slug = slug_clean

    db.flush()
    write_audit(
        db,
        actor=user,
        action="taxonomy.category_update",
        entity_type="category",
        entity_id=cat.id,
        before=before_state,
        after={"name": cat.name, "slug": cat.slug, "description": cat.description}
    )
    if before_state["name"] != cat.name or before_state["slug"] != cat.slug:
        affected_doc_ids = [
            row[0]
            for row in db.query(Document.id)
            .filter(
                Document.category_id == cat.id,
                Document.status == "published",
                Document.deleted_at.is_(None),
            )
            .all()
        ]
        if affected_doc_ids:
            emit_taxonomy_reindex_jobs(db, affected_doc_ids)

    db.commit()
    return {"id": cat.id, "name": cat.name, "slug": cat.slug, "description": cat.description}

def admin_delete_category(db: Session, cat_id: str, user: User):
    cat = db.query(Category).filter(Category.id == cat_id).first()
    if not cat:
        raise AppException(status_code=404, code="CATEGORY_NOT_FOUND", message="Category not found")

    doc_count = db.query(Document).filter(Document.category_id == cat_id).count()
    if doc_count > 0:
        raise AppException(
            status_code=409,
            code="CATEGORY_IN_USE",
            message=f"Cannot delete category: {doc_count} document(s) are currently assigned to it."
        )

    write_audit(db, actor=user, action="taxonomy.category_delete", entity_type="category", entity_id=cat.id, before={"name": cat.name, "slug": cat.slug})
    db.delete(cat)
    db.commit()

def admin_list_tags(db: Session, q: Optional[str] = None, page: int = 1, page_size: int = 50) -> Tuple[List[dict], int]:
    query = (
        db.query(Tag, func.count(DocumentTag.document_id).label("doc_count"))
        .outerjoin(DocumentTag, Tag.id == DocumentTag.tag_id)
        .group_by(Tag.id)
        .order_by(Tag.name.asc())
    )
    if q and q.strip():
        escaped = q.strip().replace('%', '\\%').replace('_', '\\_')
        safe_q = f"%{escaped}%"
        query = query.filter(Tag.name.ilike(safe_q))

    total = db.query(Tag).count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    results = [
        {"id": t.id, "name": t.name, "slug": t.slug, "document_count": count}
        for t, count in items
    ]
    return results, total

def admin_create_tag(db: Session, data: TagWrite, user: User) -> dict:
    if not data.name.strip():
        raise AppException(status_code=422, code="INVALID_NAME", message="Tag name cannot be empty")

    raw_slug = data.slug.strip() if data.slug and data.slug.strip() else data.name.strip()
    slug = slugify(raw_slug)
    if not slug:
        raise AppException(status_code=422, code="INVALID_SLUG", message="Tag slug cannot be empty")

    existing = db.query(Tag).filter(Tag.slug == slug).first()
    if existing:
        raise AppException(status_code=409, code="SLUG_EXISTS", message="Tag with this slug already exists")

    tag = Tag(name=data.name.strip(), slug=slug)
    db.add(tag)
    db.flush()
    write_audit(db, actor=user, action="taxonomy.tag_create", entity_type="tag", entity_id=tag.id, after={"name": tag.name, "slug": tag.slug})
    db.commit()
    return {"id": tag.id, "name": tag.name, "slug": tag.slug}

def admin_update_tag(db: Session, tag_id: str, data: TagUpdate, user: User) -> dict:
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise AppException(status_code=404, code="TAG_NOT_FOUND", message="Tag not found")

    before_state = {"name": tag.name, "slug": tag.slug}

    if data.name is not None:
        name_clean = data.name.strip()
        if not name_clean:
            raise AppException(status_code=422, code="INVALID_NAME", message="Tag name cannot be empty")
        tag.name = name_clean

    if data.slug is not None:
        slug_clean = slugify(data.slug)
        if not slug_clean:
            raise AppException(status_code=422, code="INVALID_SLUG", message="Tag slug cannot be empty")
        if slug_clean != tag.slug:
            existing = db.query(Tag).filter(Tag.slug == slug_clean).first()
            if existing:
                raise AppException(status_code=409, code="SLUG_EXISTS", message="Tag with this slug already exists")
            tag.slug = slug_clean

    db.flush()
    write_audit(
        db,
        actor=user,
        action="taxonomy.tag_update",
        entity_type="tag",
        entity_id=tag.id,
        before=before_state,
        after={"name": tag.name, "slug": tag.slug}
    )
    if before_state["name"] != tag.name or before_state["slug"] != tag.slug:
        affected_doc_ids = [
            row[0]
            for row in db.query(DocumentTag.document_id)
            .join(Document, Document.id == DocumentTag.document_id)
            .filter(
                DocumentTag.tag_id == tag.id,
                Document.status == "published",
                Document.deleted_at.is_(None),
            )
            .all()
        ]
        if affected_doc_ids:
            emit_taxonomy_reindex_jobs(db, affected_doc_ids)

    db.commit()
    return {"id": tag.id, "name": tag.name, "slug": tag.slug}

def admin_delete_tag(db: Session, tag_id: str, user: User):
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise AppException(status_code=404, code="TAG_NOT_FOUND", message="Tag not found")

    usage_count = db.query(DocumentTag).filter(DocumentTag.tag_id == tag_id).count()
    if usage_count > 0:
        raise AppException(
            status_code=409,
            code="TAG_IN_USE",
            message=f"Cannot delete tag: {usage_count} document(s) are currently tagged with it."
        )

    write_audit(db, actor=user, action="taxonomy.tag_delete", entity_type="tag", entity_id=tag.id, before={"name": tag.name, "slug": tag.slug})
    db.delete(tag)
    db.commit()
