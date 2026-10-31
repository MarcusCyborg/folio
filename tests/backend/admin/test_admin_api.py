import uuid
from datetime import date
from src.backend.models.document import Document
from src.backend.models.taxonomy import Category, Tag
from src.backend.models.comment import Comment, Report
from src.backend.models.auth import User

def auth_login(client, email, password="FolioDemo2026!"):
    sess = client.get("/api/v1/auth/session").json()
    res = client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": sess["csrf_token"]},
        json={"email": email, "password": password}
    )
    assert res.status_code == 200
    return res.json()["csrf_token"]

def test_rbac_permission_matrix_enforcement(client):
    # Member -> 403 on admin
    csrf_member = auth_login(client, "reader@folio.test")
    res_m = client.get("/api/v1/admin/documents")
    assert res_m.status_code == 403

    # Content Manager -> can access documents and taxonomy, 403 on users and moderation
    csrf_cm = auth_login(client, "content@folio.test")
    assert client.get("/api/v1/admin/documents").status_code == 200
    assert client.get("/api/v1/admin/categories").status_code == 200
    assert client.get("/api/v1/admin/users").status_code == 403
    assert client.get("/api/v1/admin/comments").status_code == 403
    assert client.get("/api/v1/admin/analytics/overview").status_code == 403

    # Moderator -> can access moderation comments/reports, 403 on documents
    csrf_mod = auth_login(client, "moderator@folio.test")
    assert client.get("/api/v1/admin/comments").status_code == 200
    assert client.get("/api/v1/admin/reports").status_code == 200
    assert client.post("/api/v1/admin/documents", headers={"X-CSRF-Token": csrf_mod}, json={"title": "fail"}).status_code == 403

    # Data SEO -> can access SEO and analytics, 403 on document content writes and users
    csrf_seo = auth_login(client, "seo@folio.test")
    assert client.get("/api/v1/admin/analytics/overview").status_code == 200
    assert client.post("/api/v1/admin/documents", headers={"X-CSRF-Token": csrf_seo}, json={"title": "fail"}).status_code == 403

    # Super Admin -> 200 on all
    csrf_admin = auth_login(client, "admin@folio.test")
    assert client.get("/api/v1/admin/users").status_code == 200
    assert client.get("/api/v1/admin/roles").status_code == 200
    assert client.get("/api/v1/admin/audit-logs").status_code == 200
    assert client.get("/api/v1/admin/settings").status_code == 200

def test_document_full_crud_workflow(client, db_session):
    csrf = auth_login(client, "content@folio.test")
    cat = db_session.query(Category).first()
    tag = db_session.query(Tag).first()

    # 1. Create document (starts as draft)
    create_res = client.post(
        "/api/v1/admin/documents",
        headers={"X-CSRF-Token": csrf},
        json={
            "title": "Quantum Error Correction Protocols",
            "content": "# Quantum Error Correction\n\nDetailed theoretical overview of surface codes.",
            "summary": "Overview of surface codes and fault-tolerant quantum computing architectures.",
            "category_id": cat.id,
            "tag_ids": [tag.id],
            "author": "Dr. Alice Quantum",
        }
    )
    assert create_res.status_code == 201
    doc_data = create_res.json()
    doc_id = doc_data["id"]
    assert doc_data["status"] == "draft"
    assert doc_data["published_at"] is None

    # Draft should not be in public library
    pub_res = client.get(f"/api/v1/documents/{doc_id}")
    assert pub_res.status_code == 404

    # 2. Edit document
    edit_res = client.patch(
        f"/api/v1/admin/documents/{doc_id}",
        headers={"X-CSRF-Token": csrf},
        json={"title": "Quantum Error Correction Protocols (Revised Edition)"}
    )
    assert edit_res.status_code == 200
    assert edit_res.json()["title"] == "Quantum Error Correction Protocols (Revised Edition)"

    # 3. Publish document
    pub_action = client.patch(
        f"/api/v1/admin/documents/{doc_id}/status",
        headers={"X-CSRF-Token": csrf},
        json={"status": "published"}
    )
    assert pub_action.status_code == 200
    assert pub_action.json()["status"] == "published"
    assert pub_action.json()["published_at"] is not None

    # Now it must be visible in public library!
    pub_check = client.get(f"/api/v1/documents/{doc_id}")
    assert pub_check.status_code == 200
    assert pub_check.json()["title"] == "Quantum Error Correction Protocols (Revised Edition)"

    # 4. Unpublish (back to draft)
    unpub = client.patch(
        f"/api/v1/admin/documents/{doc_id}/status",
        headers={"X-CSRF-Token": csrf},
        json={"status": "draft"}
    )
    assert unpub.status_code == 200
    assert unpub.json()["status"] == "draft"
    assert client.get(f"/api/v1/documents/{doc_id}").status_code == 404

    # 5. Soft Delete
    del_res = client.delete(f"/api/v1/admin/documents/{doc_id}", headers={"X-CSRF-Token": csrf})
    assert del_res.status_code == 204
    assert client.get(f"/api/v1/admin/documents/{doc_id}").status_code == 404

def test_taxonomy_crud_and_conflict_protection(client, db_session):
    csrf = auth_login(client, "content@folio.test")

    # Create new category
    res_cat = client.post(
        "/api/v1/admin/categories",
        headers={"X-CSRF-Token": csrf},
        json={"name": "Quantum Computing", "description": "Quantum physics and algorithms"}
    )
    assert res_cat.status_code == 201
    cat_id = res_cat.json()["id"]

    # Delete unused category -> succeeds 204
    del_cat = client.delete(f"/api/v1/admin/categories/{cat_id}", headers={"X-CSRF-Token": csrf})
    assert del_cat.status_code == 204

    # Attempt to delete a category that has documents assigned -> 409
    used_cat = db_session.query(Category).join(Document, Category.id == Document.category_id).first()
    assert used_cat is not None
    del_used = client.delete(f"/api/v1/admin/categories/{used_cat.id}", headers={"X-CSRF-Token": csrf})
    assert del_used.status_code == 409
    assert del_used.json()["error"]["code"] == "CATEGORY_IN_USE"

def test_last_super_admin_protection(client, db_session):
    csrf = auth_login(client, "admin@folio.test")
    admin_user = db_session.query(User).filter(User.username == "admin").first()
    assert admin_user is not None

    # Attempt to demote the sole active super_admin -> 400
    demote_res = client.patch(
        f"/api/v1/admin/users/{admin_user.id}",
        headers={"X-CSRF-Token": csrf},
        json={"role_key": "member"}
    )
    assert demote_res.status_code == 400
    assert demote_res.json()["error"]["code"] == "CANNOT_DEMOTE_LAST_ADMIN"

    # Attempt to deactivate the sole active super_admin -> 400
    deact_res = client.patch(
        f"/api/v1/admin/users/{admin_user.id}",
        headers={"X-CSRF-Token": csrf},
        json={"is_active": False}
    )
    assert deact_res.status_code == 400
    assert deact_res.json()["error"]["code"] == "CANNOT_DEMOTE_LAST_ADMIN"

def test_role_permissions_management(client):
    csrf = auth_login(client, "admin@folio.test")

    # Cannot modify protected super_admin role permissions -> 400
    res_prot = client.put(
        "/api/v1/admin/roles/super_admin/permissions",
        headers={"X-CSRF-Token": csrf},
        json={"permissions": ["documents:write"]}
    )
    assert res_prot.status_code == 400
    assert res_prot.json()["error"]["code"] == "PROTECTED_ROLE"

    # Update content_manager permissions
    res_cm = client.put(
        "/api/v1/admin/roles/content_manager/permissions",
        headers={"X-CSRF-Token": csrf},
        json={"permissions": ["documents:write", "taxonomy:write", "seo:write"]}
    )
    assert res_cm.status_code == 200
    assert "seo:write" in res_cm.json()["permissions"]

def test_moderation_actions_and_suspension(client, db_session):
    # Setup comment and report
    doc = db_session.query(Document).filter(Document.status == "published").first()
    reader = db_session.query(User).filter(User.username == "reader").first()
    
    comment = Comment(document_id=doc.id, user_id=reader.id, body="Potentially spammy comment", status="visible")
    db_session.add(comment)
    db_session.flush()

    report = Report(comment_id=comment.id, reporter_id=reader.id, reason="spam", details="Commercial link", status="open")
    db_session.add(report)
    db_session.commit()

    csrf = auth_login(client, "moderator@folio.test")

    # 1. Resolve report by marking comment as spam
    res_resolve = client.patch(
        f"/api/v1/admin/reports/{report.id}",
        headers={"X-CSRF-Token": csrf},
        json={"action": "mark_spam", "resolution": "Confirmed spam domain"}
    )
    assert res_resolve.status_code == 200
    assert res_resolve.json()["status"] == "resolved"

    # Comment in DB must now be spam!
    db_session.refresh(comment)
    assert comment.status == "spam"

    # 2. Suspend commenting for reader
    suspend_res = client.patch(
        f"/api/v1/admin/users/{reader.id}/commenting",
        headers={"X-CSRF-Token": csrf},
        json={"suspended_until": "2026-12-31T23:59:59Z", "reason": "Repeated spamming"}
    )
    assert suspend_res.status_code == 200
    assert suspend_res.json()["commenting_suspended_until"] is not None

def test_seo_and_analytics_dashboard(client, db_session):
    doc = db_session.query(Document).filter(Document.status == "published").first()
    csrf_seo = auth_login(client, "seo@folio.test")

    # 1. Update SEO metadata (does not change body or status)
    seo_res = client.patch(
        f"/api/v1/admin/documents/{doc.id}/seo",
        headers={"X-CSRF-Token": csrf_seo},
        json={
            "seo_title": "Optimized Search Engine Title",
            "seo_description": "Search engine snippet description for researchers",
            "seo_keywords": ["ai", "deep-learning", "quantum"],
            "cover_image_alt": "Diagram of quantum neural network",
        }
    )
    assert seo_res.status_code == 200
    data = seo_res.json()
    assert data["seo_title"] == "Optimized Search Engine Title"
    assert "quantum" in data["seo_keywords"]

    # 2. Analytics overview
    analytics_res = client.get("/api/v1/admin/analytics/overview")
    assert analytics_res.status_code == 200
    a_data = analytics_res.json()
    assert "totals" in a_data
    assert a_data["totals"]["published_documents"] >= 100
    assert "daily" in a_data
    assert len(a_data["daily"]) >= 30  # Daily series with zero-filling!

def test_settings_and_audit_trail(client):
    csrf = auth_login(client, "admin@folio.test")

    # Update site settings
    patch_settings = client.patch(
        "/api/v1/admin/settings",
        headers={"X-CSRF-Token": csrf},
        json={"site_name": "Folio Research Portal 2026"}
    )
    assert patch_settings.status_code == 200
    assert patch_settings.json()["site_name"] == "Folio Research Portal 2026"

    # Verify audit log recorded
    audit_res = client.get("/api/v1/admin/audit-logs?page=1&page_size=10")
    assert audit_res.status_code == 200
    logs = audit_res.json()["items"]
    assert len(logs) > 0
    assert any("settings" in l["action"] or "document" in l["action"] for l in logs)
