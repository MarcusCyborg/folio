import pytest
from src.backend.models.document import Document
from src.backend.models.system import AuditLog
from src.backend.models.auth import User
from src.backend.core.audit import write_audit

def auth_login(client, email, password="FolioDemo2026!"):
    sess = client.get("/api/v1/auth/session").json()
    res = client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": sess["csrf_token"]},
        json={"email": email, "password": password}
    )
    assert res.status_code == 200
    return res.json()["csrf_token"]

def test_seo_metadata_persistence_and_isolation(client, db_session):
    doc = db_session.query(Document).filter(Document.status == "published").first()
    original_title = doc.title
    original_content = doc.content
    original_status = doc.status

    csrf_seo = auth_login(client, "admin@folio.test")

    # 1. Update SEO metadata
    seo_res = client.patch(
        f"/api/v1/admin/documents/{doc.id}/seo",
        headers={"X-CSRF-Token": csrf_seo},
        json={
            "seo_title": "Optimized Academic Title for Folio",
            "seo_description": "Comprehensive study and research metadata description",
            "seo_keywords": ["research", "science", "peer-reviewed"],
            "cover_image_alt": "Illustration of research laboratory equipment",
        }
    )
    assert seo_res.status_code == 200
    data = seo_res.json()
    assert data["seo_title"] == "Optimized Academic Title for Folio"
    assert data["seo_description"] == "Comprehensive study and research metadata description"
    assert "peer-reviewed" in data["seo_keywords"]
    assert data["cover_image_alt"] == "Illustration of research laboratory equipment"

    # 2. Verify content, title, and status remain UNCHANGED
    db_session.refresh(doc)
    assert doc.title == original_title
    assert doc.content == original_content
    assert doc.status == original_status

def test_settings_validation_and_audit_redaction(client, db_session):
    csrf_admin = auth_login(client, "admin@folio.test")

    # 1. Update allowed settings
    patch_settings = client.patch(
        "/api/v1/admin/settings",
        headers={"X-CSRF-Token": csrf_admin},
        json={
            "site_name": "Folio Research Portal 2026",
            "site_description": "Curated enterprise repository for verified research",
            "registration_enabled": True,
            "comments_enabled": True,
        }
    )
    assert patch_settings.status_code == 200
    assert patch_settings.json()["site_name"] == "Folio Research Portal 2026"

    # 2. Blank site_name rejected with 422
    bad_settings = client.patch(
        "/api/v1/admin/settings",
        headers={"X-CSRF-Token": csrf_admin},
        json={"site_name": "   "}
    )
    assert bad_settings.status_code == 422

    # 3. Audit logs redaction verification
    # Manually write an audit entry with sensitive data to test redaction
    admin_user = db_session.query(User).filter(User.username == "admin").first()
    write_audit(
        db_session,
        actor=admin_user,
        action="user.password_reset",
        entity_type="user",
        entity_id=admin_user.id,
        before={"password_hash": "$argon2id$secret_hash_value"},
        after={"token": "raw_session_token_12345", "csrf_token": "csrf_token_secret"}
    )
    db_session.commit()

    # Query audit logs via API
    logs_res = client.get("/api/v1/admin/audit-logs?page=1&page_size=50")
    assert logs_res.status_code == 200
    items = logs_res.json()["items"]

    # Verify no plaintext sensitive keys appear in any audit log
    for item in items:
        item_str = str(item)
        assert "$argon2id$secret_hash_value" not in item_str
        assert "raw_session_token_12345" not in item_str
        assert "csrf_token_secret" not in item_str

    # 4. Inverted date range in audit logs returns 422
    bad_audit_dates = client.get("/api/v1/admin/audit-logs?date_from=2026-10-31&date_to=2026-10-01")
    assert bad_audit_dates.status_code == 422
    assert bad_audit_dates.json()["error"]["code"] == "INVALID_DATE_RANGE"

def test_audit_log_transaction_rollback_guarantee(client, db_session):
    """Ensures transaction rollback does NOT leave a fake successful audit log."""
    csrf_admin = auth_login(client, "admin@folio.test")
    admin_user = db_session.query(User).filter(User.username == "admin").first()

    count_before = db_session.query(AuditLog).filter(AuditLog.action.like("%cannot_demote%")).count()

    # Attempt an invalid operation that fails (e.g., demoting sole super admin)
    res = client.patch(
        f"/api/v1/admin/users/{admin_user.id}",
        headers={"X-CSRF-Token": csrf_admin},
        json={"role_key": "member"}
    )
    assert res.status_code == 400

    # Ensure no audit log entry for demotion exists
    count_after = db_session.query(AuditLog).filter(AuditLog.action.like("%cannot_demote%")).count()
    assert count_after == count_before
