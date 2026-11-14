import uuid
from datetime import datetime, timedelta, timezone

def test_end_to_end_research_library_lifecycle(client):
    """
    Comprehensive End-to-End integration test covering the complete Folio lifecycle:
    1. Super Admin creates category, creates draft, verifies invisibility, then publishes.
    2. Reader searches for document, receives search_event_id, logs click and view event.
    3. Reader likes document, posts a comment with mention.
    4. Member reports comment.
    5. Super Admin resolves report (hides comment) and temporarily suspends commenting for reader.
    6. Reader is blocked from commenting while suspended.
    7. Super Admin sets custom SEO metadata and inspects analytics dashboard.
    8. Super Admin checks audit trail and updates global settings.
    """
    # -------------------------------------------------------------------------
    # 1. Super Admin creates category, creates document, publishes
    # -------------------------------------------------------------------------
    session_res = client.get("/api/v1/auth/session")
    csrf_token = session_res.json()["csrf_token"]

    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@folio.test", "password": "FolioDemo2026!"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert login_res.status_code == 200
    csrf_token = login_res.json()["csrf_token"]

    cat_res = client.post(
        "/api/v1/admin/categories",
        json={"name": "Quantum Tech", "description": "Quantum Computing & Information Theory"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert cat_res.status_code == 201
    category_id = cat_res.json()["id"]

    doc_res = client.post(
        "/api/v1/admin/documents",
        json={
            "title": "Quantum Supremacy in Superconducting Qubits",
            "content": "## Introduction\n\nQuantum supremacy represents a major milestone in physics.",
            "summary": "Demonstration of computational advantage using superconducting quantum processors.",
            "category_id": category_id,
            "tag_ids": [],
            "author": "Dr. Eleanor Vance",
            "source_attribution": "Wikipedia: Quantum Supremacy",
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    assert doc_res.status_code == 201
    doc_data = doc_res.json()
    doc_id = doc_data["id"]
    assert doc_data["status"] == "draft"

    # Verify document is NOT visible to public search while in draft
    pub_search = client.get("/api/v1/documents?q=Superconducting")
    assert pub_search.status_code == 200
    assert not any(item["id"] == doc_id for item in pub_search.json()["items"])

    # Publish document
    pub_res = client.patch(
        f"/api/v1/admin/documents/{doc_id}/status",
        json={"status": "published"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert pub_res.status_code == 200
    assert pub_res.json()["status"] == "published"

    # -------------------------------------------------------------------------
    # 2. Reader performs search, click, view, like, and comment
    # -------------------------------------------------------------------------
    # Login as reader
    login_reader = client.post(
        "/api/v1/auth/login",
        json={"email": "reader@folio.test", "password": "FolioDemo2026!"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert login_reader.status_code == 200
    reader_user = login_reader.json()["user"]
    reader_id = reader_user["id"]
    csrf_token = login_reader.json()["csrf_token"]

    # Public search
    search_res = client.get("/api/v1/documents?q=Superconducting")
    assert search_res.status_code == 200
    search_data = search_res.json()
    assert search_data["total"] >= 1
    assert any(item["id"] == doc_id for item in search_data["items"])
    search_event_id = search_data["search_event_id"]
    assert search_event_id is not None

    # Log click event
    click_res = client.post(
        "/api/v1/events/clicks",
        json={
            "search_event_id": search_event_id,
            "document_id": doc_id,
            "request_key": str(uuid.uuid4()),
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    assert click_res.status_code == 201

    # Log view event
    view_res = client.post(
        f"/api/v1/documents/{doc_id}/views",
        json={"navigation_id": str(uuid.uuid4())},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert view_res.status_code == 200
    assert view_res.json()["views_count"] >= 1

    # Like document
    like_res = client.put(
        f"/api/v1/documents/{doc_id}/like",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert like_res.status_code == 200
    assert like_res.json()["liked_by_me"] is True

    # Post comment with mention @admin
    comment_res = client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"body": "Fascinating quantum results, cc @admin for review!"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert comment_res.status_code == 201
    comment_data = comment_res.json()
    comment_id = comment_data["id"]
    assert any(m["username"] == "admin" for m in comment_data["mentions"])

    # -------------------------------------------------------------------------
    # 3. Member reports the comment
    # -------------------------------------------------------------------------
    report_res = client.post(
        f"/api/v1/comments/{comment_id}/reports",
        json={"reason": "Contains promotional speculation", "details": "Please review quantum claim validity."},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert report_res.status_code == 201
    report_id = report_res.json()["id"]

    # -------------------------------------------------------------------------
    # 4. Super Admin reviews report, hides comment, and suspends user commenting
    # -------------------------------------------------------------------------
    login_mod = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@folio.test", "password": "FolioDemo2026!"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert login_mod.status_code == 200
    csrf_token = login_mod.json()["csrf_token"]

    resolve_res = client.patch(
        f"/api/v1/admin/reports/{report_id}",
        json={"action": "hide_comment", "resolution": "Hidden pending factual review"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert resolve_res.status_code == 200

    # Suspend commenting for reader for 3 days
    suspended_until = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    suspend_res = client.patch(
        f"/api/v1/admin/users/{reader_id}/commenting",
        json={"suspended_until": suspended_until, "reason": "Violated discussion quality standards"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert suspend_res.status_code == 200

    # -------------------------------------------------------------------------
    # 5. Verify reader commenting suspension is actively enforced
    # -------------------------------------------------------------------------
    # Switch back to reader
    login_reader2 = client.post(
        "/api/v1/auth/login",
        json={"email": "reader@folio.test", "password": "FolioDemo2026!"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert login_reader2.status_code == 200
    csrf_token = login_reader2.json()["csrf_token"]

    blocked_comment = client.post(
        f"/api/v1/documents/{doc_id}/comments",
        json={"body": "Trying to comment while suspended"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert blocked_comment.status_code == 403
    assert "suspended" in blocked_comment.text.lower()

    # -------------------------------------------------------------------------
    # 6. Super Admin edits SEO metadata and checks analytics
    # -------------------------------------------------------------------------
    login_seo = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@folio.test", "password": "FolioDemo2026!"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert login_seo.status_code == 200
    csrf_token = login_seo.json()["csrf_token"]

    seo_update = client.patch(
        f"/api/v1/admin/documents/{doc_id}/seo",
        json={
            "seo_title": "Quantum Supremacy Guide: Qubits & Advantage",
            "seo_description": "Comprehensive analysis of superconducting qubits achieving quantum supremacy.",
            "seo_keywords": ["quantum", "qubits", "supremacy", "physics"],
            "cover_image_alt": "Micrograph of superconducting quantum circuit",
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    assert seo_update.status_code == 200
    assert seo_update.json()["seo_title"] == "Quantum Supremacy Guide: Qubits & Advantage"

    # Check analytics overview
    analytics_res = client.get("/api/v1/admin/analytics/overview")
    assert analytics_res.status_code == 200
    analytics_data = analytics_res.json()
    assert analytics_data["totals"]["published_documents"] >= 1
    assert analytics_data["totals"]["search_requests"] >= 1
    assert analytics_data["totals"]["result_clicks"] >= 1

    # -------------------------------------------------------------------------
    # 7. Super Admin verifies audit trail and settings
    # -------------------------------------------------------------------------
    login_admin = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@folio.test", "password": "FolioDemo2026!"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert login_admin.status_code == 200
    csrf_token = login_admin.json()["csrf_token"]

    audit_res = client.get("/api/v1/admin/audit-logs")
    assert audit_res.status_code == 200
    logs = audit_res.json()["items"]
    assert len(logs) > 0
    # Verify various actions were captured in audit log
    actions_logged = {l["action"] for l in logs}
    assert any("create" in a or "update" in a for a in actions_logged)

    # Update global settings
    settings_res = client.patch(
        "/api/v1/admin/settings",
        json={"site_name": "Folio Research Archives", "comments_enabled": True},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert settings_res.status_code == 200
    assert settings_res.json()["site_name"] == "Folio Research Archives"
