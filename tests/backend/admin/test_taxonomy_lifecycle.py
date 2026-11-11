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

def test_category_crud_slug_uniqueness_and_conflict(client, db_session):
    csrf = auth_login(client, "content@folio.test")

    # 1. Create category with custom slug
    res1 = client.post(
        "/api/v1/admin/categories",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Computational Neuroscience",
            "slug": "comp-neuro",
            "description": "Brain modeling and neural dynamics"
        }
    )
    assert res1.status_code == 201
    cat1_id = res1.json()["id"]
    assert res1.json()["slug"] == "comp-neuro"

    # 2. Reject duplicate slug -> 409
    res_dup = client.post(
        "/api/v1/admin/categories",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Computer Neuroscience Duplicate",
            "slug": "comp-neuro"
        }
    )
    assert res_dup.status_code == 409
    assert res_dup.json()["error"]["code"] == "SLUG_EXISTS"

    # 3. Category with 0 documents appears in admin categories list with document_count == 0
    cat_list = client.get("/api/v1/admin/categories?page=1&page_size=100").json()
    found = next((c for c in cat_list["items"] if c["id"] == cat1_id), None)
    assert found is not None
    assert found["document_count"] == 0

    # 4. Partial update (PATCH): only description
    res_patch = client.patch(
        f"/api/v1/admin/categories/{cat1_id}",
        headers={"X-CSRF-Token": csrf},
        json={"description": "Updated neural networks and synaptic plasticity"}
    )
    assert res_patch.status_code == 200
    assert res_patch.json()["description"] == "Updated neural networks and synaptic plasticity"
    assert res_patch.json()["name"] == "Computational Neuroscience"
    assert res_patch.json()["slug"] == "comp-neuro"

    # 5. Delete unused category -> succeeds with 204
    del_res = client.delete(
        f"/api/v1/admin/categories/{cat1_id}",
        headers={"X-CSRF-Token": csrf}
    )
    assert del_res.status_code == 204

    # 6. Attempt to delete category in use by documents -> 409 CATEGORY_IN_USE
    used_cat = db_session.query(Category).join(Document, Category.id == Document.category_id).first()
    assert used_cat is not None
    del_used = client.delete(
        f"/api/v1/admin/categories/{used_cat.id}",
        headers={"X-CSRF-Token": csrf}
    )
    assert del_used.status_code == 409
    assert del_used.json()["error"]["code"] == "CATEGORY_IN_USE"

def test_tag_crud_slug_uniqueness_and_conflict(client, db_session):
    csrf = auth_login(client, "content@folio.test")

    # 1. Create tag
    res_tag = client.post(
        "/api/v1/admin/tags",
        headers={"X-CSRF-Token": csrf},
        json={"name": "Reinforcement Learning", "slug": "reinforcement-learning"}
    )
    assert res_tag.status_code == 201
    tag_id = res_tag.json()["id"]

    # 2. Reject duplicate tag slug -> 409
    res_tag_dup = client.post(
        "/api/v1/admin/tags",
        headers={"X-CSRF-Token": csrf},
        json={"name": "RL Duplicate", "slug": "reinforcement-learning"}
    )
    assert res_tag_dup.status_code == 409
    assert res_tag_dup.json()["error"]["code"] == "SLUG_EXISTS"

    # 3. Unused tag appears in admin tags list with document_count == 0
    tag_list = client.get("/api/v1/admin/tags?page=1&page_size=100").json()
    found_tag = next((t for t in tag_list["items"] if t["id"] == tag_id), None)
    assert found_tag is not None
    assert found_tag["document_count"] == 0

    # 4. Partial update (PATCH): change name only
    res_patch_tag = client.patch(
        f"/api/v1/admin/tags/{tag_id}",
        headers={"X-CSRF-Token": csrf},
        json={"name": "Deep Reinforcement Learning"}
    )
    assert res_patch_tag.status_code == 200
    assert res_patch_tag.json()["name"] == "Deep Reinforcement Learning"
    assert res_patch_tag.json()["slug"] == "reinforcement-learning"

    # 5. Delete unused tag -> 204
    assert client.delete(f"/api/v1/admin/tags/{tag_id}", headers={"X-CSRF-Token": csrf}).status_code == 204

    # 6. Delete tag currently assigned to documents -> 409 TAG_IN_USE
    used_tag = db_session.query(Tag).filter(Tag.document_tags.any()).first()
    if used_tag:
        del_used_tag = client.delete(
            f"/api/v1/admin/tags/{used_tag.id}",
            headers={"X-CSRF-Token": csrf}
        )
        assert del_used_tag.status_code == 409
        assert del_used_tag.json()["error"]["code"] == "TAG_IN_USE"


def test_b07_admin_tags_filtered_total_and_pagination_beyond_100(client, db_session):
    """R07 / B07: GET /api/v1/admin/tags?q= returns exact filtered total and paginates >100 tags."""
    csrf = auth_login(client, "content@folio.test")
    tags = [
        Tag(name=f"BatchTag Alpha {i:03d}", slug=f"batchtag-alpha-{i:03d}")
        for i in range(105)
    ] + [
        Tag(name=f"OtherTag Beta {i:03d}", slug=f"othertag-beta-{i:03d}")
        for i in range(10)
    ]
    db_session.add_all(tags)
    db_session.commit()

    # Filtered query must return total=105 (not total across all tags)
    res_filtered = client.get("/api/v1/admin/tags?q=BatchTag+Alpha&page=1&page_size=50")
    assert res_filtered.status_code == 200
    data1 = res_filtered.json()
    assert data1["total"] == 105
    assert len(data1["items"]) == 50

    # Page 3 reaches items 101..105
    res_page3 = client.get("/api/v1/admin/tags?q=BatchTag+Alpha&page=3&page_size=50")
    assert res_page3.status_code == 200
    data3 = res_page3.json()
    assert data3["total"] == 105
    assert len(data3["items"]) == 5

    # Wildcard escaping on q
    res_empty = client.get("/api/v1/admin/tags?q=BatchTag%25Alpha&page=1&page_size=50")
    assert res_empty.status_code == 200
    assert res_empty.json()["total"] == 0
