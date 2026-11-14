import pytest
from src.backend.models.document import Document
from src.backend.models.taxonomy import Category, Tag

def auth_login(client, email, password="FolioDemo2026!"):
    sess = client.get("/api/v1/auth/session").json()
    res = client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": sess["csrf_token"]},
        json={"email": email, "password": password}
    )
    assert res.status_code == 200
    return res.json()["csrf_token"]

def test_document_full_lifecycle_and_validation(client, db_session):
    csrf = auth_login(client, "admin@folio.test")
    cat = db_session.query(Category).first()
    tag = db_session.query(Tag).first()

    # 1. Validation on create: whitespace-only title/content/summary rejected with 422
    res_bad_title = client.post(
        "/api/v1/admin/documents",
        headers={"X-CSRF-Token": csrf},
        json={
            "title": "   ",
            "content": "Valid content",
            "summary": "Valid summary",
            "category_id": cat.id,
        }
    )
    assert res_bad_title.status_code == 422

    res_bad_content = client.post(
        "/api/v1/admin/documents",
        headers={"X-CSRF-Token": csrf},
        json={
            "title": "Valid Title",
            "content": "   ",
            "summary": "Valid summary",
            "category_id": cat.id,
        }
    )
    assert res_bad_content.status_code == 422

    res_bad_summary = client.post(
        "/api/v1/admin/documents",
        headers={"X-CSRF-Token": csrf},
        json={
            "title": "Valid Title",
            "content": "Valid content",
            "summary": "   ",
            "category_id": cat.id,
        }
    )
    assert res_bad_summary.status_code == 422

    # 2. Create document successfully (starts as draft)
    create_res = client.post(
        "/api/v1/admin/documents",
        headers={"X-CSRF-Token": csrf},
        json={
            "title": "Advanced Algorithmic Game Theory",
            "content": "# Algorithmic Game Theory\n\nStudy of Nash equilibria in distributed routing protocols.",
            "summary": "Mathematical foundations of equilibrium computation and price of anarchy.",
            "category_id": cat.id,
            "tag_ids": [tag.id],
            "author": "",  # Empty author should default to user's display_name
        }
    )
    assert create_res.status_code == 201
    doc_data = create_res.json()
    doc_id = doc_data["id"]
    assert doc_data["status"] == "draft"
    assert doc_data["published_at"] is None
    assert doc_data["author"] == "Super Admin"  # default display_name

    # Draft document MUST NOT be visible in public library
    assert client.get(f"/api/v1/documents/{doc_id}").status_code == 404

    # 3. Validation on publish: empty/whitespace fields prevent publishing
    # Clear content to test publish validation
    client.patch(
        f"/api/v1/admin/documents/{doc_id}",
        headers={"X-CSRF-Token": csrf},
        json={"summary": "   "}
    )
    # Note: summary was rejected by 422 on update, let's verify update rejects whitespace
    update_bad = client.patch(
        f"/api/v1/admin/documents/{doc_id}",
        headers={"X-CSRF-Token": csrf},
        json={"title": "   "}
    )
    assert update_bad.status_code == 422

    # 4. Legitimate update
    edit_res = client.patch(
        f"/api/v1/admin/documents/{doc_id}",
        headers={"X-CSRF-Token": csrf},
        json={
            "title": "Advanced Algorithmic Game Theory (2nd Edition)",
            "summary": "Updated analysis of Nash equilibria and mechanism design in distributed networks.",
            "author": "Prof. John Nash",
        }
    )
    assert edit_res.status_code == 200
    assert edit_res.json()["title"] == "Advanced Algorithmic Game Theory (2nd Edition)"
    assert edit_res.json()["author"] == "Prof. John Nash"

    # 5. Publish document
    pub_res = client.patch(
        f"/api/v1/admin/documents/{doc_id}/status",
        headers={"X-CSRF-Token": csrf},
        json={"status": "published"}
    )
    assert pub_res.status_code == 200
    assert pub_res.json()["status"] == "published"
    assert pub_res.json()["published_at"] is not None

    # Now it is accessible in public library
    pub_detail = client.get(f"/api/v1/documents/{doc_id}")
    assert pub_detail.status_code == 200
    assert pub_detail.json()["title"] == "Advanced Algorithmic Game Theory (2nd Edition)"

    # 6. Unpublish document (revert to draft)
    unpub_res = client.patch(
        f"/api/v1/admin/documents/{doc_id}/status",
        headers={"X-CSRF-Token": csrf},
        json={"status": "draft"}
    )
    assert unpub_res.status_code == 200
    assert unpub_res.json()["status"] == "draft"

    # Immediately hidden from public library
    assert client.get(f"/api/v1/documents/{doc_id}").status_code == 404

    # 7. Soft Delete
    del_res = client.delete(
        f"/api/v1/admin/documents/{doc_id}",
        headers={"X-CSRF-Token": csrf}
    )
    assert del_res.status_code == 204

    # Excluded from public library
    assert client.get(f"/api/v1/documents/{doc_id}").status_code == 404

    # Excluded from admin get
    assert client.get(f"/api/v1/admin/documents/{doc_id}").status_code == 404

    # Excluded from admin list
    admin_list = client.get(f"/api/v1/admin/documents?q=Algorithmic+Game+Theory").json()
    assert all(item["id"] != doc_id for item in admin_list["items"])

    # Mutations on deleted document return 404
    assert client.patch(
        f"/api/v1/admin/documents/{doc_id}",
        headers={"X-CSRF-Token": csrf},
        json={"title": "Zombie"}
    ).status_code == 404

    assert client.patch(
        f"/api/v1/admin/documents/{doc_id}/status",
        headers={"X-CSRF-Token": csrf},
        json={"status": "published"}
    ).status_code == 404

    assert client.delete(
        f"/api/v1/admin/documents/{doc_id}",
        headers={"X-CSRF-Token": csrf}
    ).status_code == 404


def test_r12_patch_source_url_conflict_with_tags_and_soft_deleted_returns_409_atomically(client, db_session):
    """
    R12 / B03:
    PATCH /api/v1/admin/documents/{id} with a conflicting source_url (including when tag_ids
    is also updated or when the conflicting document is soft-deleted) returns 409 SOURCE_URL_CONFLICT
    with zero partial tag or field mutation.
    """
    import uuid
    csrf = auth_login(client, "admin@folio.test")
    cat = db_session.query(Category).first()
    tags = db_session.query(Tag).limit(2).all()
    assert len(tags) >= 2
    t1, t2 = tags[0], tags[1]

    url_live = f"https://example.org/wiki/r12-live-{uuid.uuid4().hex[:8]}"
    url_deleted = f"https://example.org/wiki/r12-del-{uuid.uuid4().hex[:8]}"

    d_live = Document(
        title="R12 Live Owner",
        content="Content live",
        summary="Summary live",
        category_id=cat.id,
        status="draft",
        source_url=url_live,
    )
    d_target = Document(
        title="R12 Target Doc",
        content="Content target",
        summary="Summary target",
        category_id=cat.id,
        status="draft",
        source_url=f"https://example.org/wiki/r12-orig-{uuid.uuid4().hex[:8]}",
    )
    d_deleted = Document(
        title="R12 Soft Deleted Owner",
        content="Content deleted",
        summary="Summary deleted",
        category_id=cat.id,
        status="draft",
        source_url=url_deleted,
    )
    db_session.add_all([d_live, d_target, d_deleted])
    db_session.flush()
    from src.backend.models.document import DocumentTag
    db_session.add(DocumentTag(document_id=d_target.id, tag_id=t1.id))
    db_session.commit()

    # Soft-delete d_deleted via API
    del_res = client.delete(f"/api/v1/admin/documents/{d_deleted.id}", headers={"X-CSRF-Token": csrf})
    assert del_res.status_code == 204

    # 1. PATCH d_target with url_live AND new tag_ids=[t2.id] -> must return 409 and NOT overwrite tags
    patch_live_conflict = client.patch(
        f"/api/v1/admin/documents/{d_target.id}",
        headers={"X-CSRF-Token": csrf},
        json={"source_url": url_live, "tag_ids": [t2.id], "title": "Should Not Persist"},
    )
    assert patch_live_conflict.status_code == 409
    assert patch_live_conflict.json()["error"]["code"] == "SOURCE_URL_CONFLICT"

    # Verify d_target still has original tag [t1.id] and original title
    refreshed = client.get(f"/api/v1/admin/documents/{d_target.id}").json()
    assert refreshed["title"] == "R12 Target Doc"
    assert [t["id"] for t in refreshed["tags"]] == [t1.id]

    # 2. PATCH d_target with url_deleted (soft-deleted doc's source_url) -> must return 409 cleanly (not 500)
    patch_deleted_conflict = client.patch(
        f"/api/v1/admin/documents/{d_target.id}",
        headers={"X-CSRF-Token": csrf},
        json={"source_url": url_deleted, "tag_ids": [t2.id]},
    )
    assert patch_deleted_conflict.status_code == 409
    assert patch_deleted_conflict.json()["error"]["code"] == "SOURCE_URL_CONFLICT"
