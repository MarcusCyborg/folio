import pytest
from src.backend.models.document import Document
from src.backend.models.taxonomy import Category
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

def test_full_rbac_permission_matrix(client, db_session):
    """Every administrative write is reserved for Super Admin."""
    cat = db_session.query(Category).first()
    doc = db_session.query(Document).filter(Document.status == 'published').first()
    reader = db_session.query(User).filter(User.username == 'reader').first()
    csrf = auth_login(client, 'reader@folio.test')
    requests = [
        ('post', '/documents', {'title': 'Denied', 'content': 'Text', 'summary': 'Summary', 'category_id': cat.id}),
        ('patch', f'/documents/{doc.id}', {'title': 'Denied'}),
        ('patch', f'/documents/{doc.id}/status', {'status': 'draft'}),
        ('delete', f'/documents/{doc.id}', None),
        ('post', '/categories', {'name': 'Denied'}),
        ('patch', f'/documents/{doc.id}/seo', {'seo_title': 'Denied'}),
        ('patch', f'/users/{reader.id}', {'role_key': 'super_admin'}),
        ('put', '/roles/member/permissions', {'permissions': ['users:manage']}),
        ('patch', '/settings', {'site_name': 'Denied'}),
        ('patch', f'/users/{reader.id}/commenting', {'reason': 'Denied'}),
    ]
    for method, endpoint, body in requests:
        response = client.request(method, '/api/v1/admin' + endpoint,
                                  headers={'X-CSRF-Token': csrf}, json=body)
        assert response.status_code == 403, endpoint

    csrf = auth_login(client, 'admin@folio.test')
    for role in ('content_manager', 'moderator', 'data_seo', 'invented_role'):
        response = client.patch(f'/api/v1/admin/users/{reader.id}',
                                headers={'X-CSRF-Token': csrf}, json={'role_key': role})
        assert response.status_code == 422
        assert response.json()['error']['code'] == 'INVALID_ROLE'
    db_session.refresh(reader)
    assert reader.role_key == 'member'

def test_mass_assignment_and_forged_fields_rejection(client, db_session):
    """Tests that server fields cannot be injected via mass assignment or forged JSON."""
    csrf_cm = auth_login(client, "admin@folio.test")
    cat = db_session.query(Category).first()

    # 1. Attempt to inject status='published' on creation -> 422 extra field forbidden
    res = client.post(
        "/api/v1/admin/documents",
        headers={"X-CSRF-Token": csrf_cm},
        json={
            "title": "Forged Publication Document",
            "content": "Valid content",
            "summary": "Valid summary",
            "category_id": cat.id,
            "status": "published",  # Forbidden field
        }
    )
    assert res.status_code == 422

    # 2. Create valid draft document
    created = client.post(
        "/api/v1/admin/documents",
        headers={"X-CSRF-Token": csrf_cm},
        json={
            "title": "Legitimate Draft Document",
            "content": "Valid content for draft",
            "summary": "Valid summary for draft",
            "category_id": cat.id,
        }
    ).json()
    doc_id = created["id"]
    assert created["status"] == "draft"

    # 3. Attempt to inject status into PATCH /documents/{id} -> 422
    patch_status = client.patch(
        f"/api/v1/admin/documents/{doc_id}",
        headers={"X-CSRF-Token": csrf_cm},
        json={"status": "published"}
    )
    assert patch_status.status_code == 422

    # 4. Attempt to inject author_id / created_by into PATCH /documents/{id} -> 422
    patch_author_id = client.patch(
        f"/api/v1/admin/documents/{doc_id}",
        headers={"X-CSRF-Token": csrf_cm},
        json={"created_by": "00000000-0000-0000-0000-000000000000"}
    )
    assert patch_author_id.status_code == 422

    # 5. Attempt to inject SEO fields into PATCH /documents/{id} -> 422
    patch_seo = client.patch(
        f"/api/v1/admin/documents/{doc_id}",
        headers={"X-CSRF-Token": csrf_cm},
        json={"seo_title": "Injected SEO"}
    )
    assert patch_seo.status_code == 422

    # 6. Attempt to inject content or status into PATCH /documents/{id}/seo -> 422
    csrf_seo = auth_login(client, "admin@folio.test")
    patch_seo_inject = client.patch(
        f"/api/v1/admin/documents/{doc_id}/seo",
        headers={"X-CSRF-Token": csrf_seo},
        json={"content": "Overridden Body by SEO", "status": "published"}
    )
    assert patch_seo_inject.status_code == 422

    # 7. Attempt to inject role_key into moderation commenting suspension -> 422
    csrf_mod = auth_login(client, "admin@folio.test")
    reader = db_session.query(User).filter(User.username == "reader").first()
    mod_inject = client.patch(
        f"/api/v1/admin/users/{reader.id}/commenting",
        headers={"X-CSRF-Token": csrf_mod},
        json={"role_key": "super_admin", "reason": "Test suspension"}
    )
    assert mod_inject.status_code == 422

    # 8. Attempt to inject password into admin user update -> 422
    csrf_admin = auth_login(client, "admin@folio.test")
    user_inject = client.patch(
        f"/api/v1/admin/users/{reader.id}",
        headers={"X-CSRF-Token": csrf_admin},
        json={"password": "hacked_password_123"}
    )
    assert user_inject.status_code == 422

    # 9. Attempt to inject unlisted setting into admin settings -> 422
    settings_inject = client.patch(
        f"/api/v1/admin/settings",
        headers={"X-CSRF-Token": csrf_admin},
        json={"secret_master_key": "injected_secret_value"}
    )
    assert settings_inject.status_code == 422
