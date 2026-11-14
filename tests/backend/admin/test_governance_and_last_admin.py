import pytest
import threading
from fastapi.testclient import TestClient
from src.backend.main import app
from src.backend.core.database import get_db
from src.backend.models.auth import User, Role, RolePermission
from src.backend.models.taxonomy import Category
from src.backend.models.document import Document
from src.backend.services.admin.governance_service import admin_update_user
from src.backend.core.exceptions import AppException
from tests.conftest import TestingSessionLocal

def auth_login(client, email, password="FolioDemo2026!"):
    sess = client.get("/api/v1/auth/session").json()
    res = client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": sess["csrf_token"]},
        json={"email": email, "password": password}
    )
    assert res.status_code == 200
    return res.json()["csrf_token"]

def test_user_management_and_immediate_effect(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        admin_client = TestClient(app, base_url="http://testserver")
        reader_client = TestClient(app, base_url="http://testserver")

        csrf_admin = auth_login(admin_client, "admin@folio.test")
        csrf_reader = auth_login(reader_client, "reader@folio.test")

        reader = db_session.query(User).filter(User.username == "reader").first()
        cat = db_session.query(Category).first()

        # 1. Promote reader to super_admin
        patch_role = admin_client.patch(
            f"/api/v1/admin/users/{reader.id}",
            headers={"X-CSRF-Token": csrf_admin},
            json={"role_key": "super_admin"}
        )
        assert patch_role.status_code == 200
        assert patch_role.json()["role_key"] == "super_admin"

        # Next request by reader -> reader now has super_admin permissions!
        create_test = reader_client.post(
            "/api/v1/admin/documents",
            headers={"X-CSRF-Token": csrf_reader},
            json={
                "title": "Document by Promoted Reader",
                "content": "Content here",
                "summary": "Summary here",
                "category_id": cat.id,
            }
        )
        assert create_test.status_code == 201

        # 2. Deactivate reader account via admin_client
        deact = admin_client.patch(
            f"/api/v1/admin/users/{reader.id}",
            headers={"X-CSRF-Token": csrf_admin},
            json={"is_active": False}
        )
        assert deact.status_code == 200
        assert deact.json()["is_active"] is False

        # Immediate next request by reader -> 403 ACCOUNT_DISABLED
        res_disabled = reader_client.patch(
            "/api/v1/auth/profile",
            headers={"X-CSRF-Token": csrf_reader},
            json={"display_name": "Ghost User"}
        )
        assert res_disabled.status_code == 403
        assert res_disabled.json()["error"]["code"] == "ACCOUNT_DISABLED"

        # Reactivate reader and demote back to member
        admin_client.patch(
            f"/api/v1/admin/users/{reader.id}",
            headers={"X-CSRF-Token": csrf_admin},
            json={"is_active": True, "role_key": "member"}
        )
    finally:
        app.dependency_overrides.clear()

def test_permission_revocation_takes_immediate_effect(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as admin_client, TestClient(app) as reader_client:
            csrf_admin = auth_login(admin_client, 'admin@folio.test')
            auth_login(reader_client, 'reader@folio.test')
            reader = db_session.query(User).filter(User.username == 'reader').first()
            url = f'/api/v1/admin/users/{reader.id}'
            headers = {'X-CSRF-Token': csrf_admin}
            assert admin_client.patch(url, headers=headers, json={'role_key': 'super_admin'}).status_code == 200
            assert reader_client.get('/api/v1/admin/documents').status_code == 200
            assert admin_client.patch(url, headers=headers, json={'role_key': 'member'}).status_code == 200
            assert reader_client.get('/api/v1/admin/documents').status_code == 403
            session = reader_client.get('/api/v1/auth/session').json()
            assert session['user']['role_key'] == 'member'
            assert session['user']['permissions'] == []
    finally:
        app.dependency_overrides.clear()

def test_last_super_admin_invariant_and_concurrency(client, db_session):
    csrf_admin = auth_login(client, "admin@folio.test")
    admin_user = db_session.query(User).filter(User.username == "admin").first()
    reader = db_session.query(User).filter(User.username == "reader").first()

    # 1. Ensure cannot demote the sole active super_admin -> 400
    demote_res = client.patch(
        f"/api/v1/admin/users/{admin_user.id}",
        headers={"X-CSRF-Token": csrf_admin},
        json={"role_key": "member"}
    )
    assert demote_res.status_code == 400
    assert demote_res.json()["error"]["code"] == "CANNOT_DEMOTE_LAST_ADMIN"

    # 2. Ensure cannot deactivate the sole active super_admin -> 400
    deact_res = client.patch(
        f"/api/v1/admin/users/{admin_user.id}",
        headers={"X-CSRF-Token": csrf_admin},
        json={"is_active": False}
    )
    assert deact_res.status_code == 400
    assert deact_res.json()["error"]["code"] == "CANNOT_DEMOTE_LAST_ADMIN"

    # 3. Promote reader to second super_admin
    promote_res = client.patch(
        f"/api/v1/admin/users/{reader.id}",
        headers={"X-CSRF-Token": csrf_admin},
        json={"role_key": "super_admin"}
    )
    assert promote_res.status_code == 200

    # Now there are 2 active super admins (admin_user and reader)
    # Demoting reader succeeds
    demote_reader = client.patch(
        f"/api/v1/admin/users/{reader.id}",
        headers={"X-CSRF-Token": csrf_admin},
        json={"role_key": "member"}
    )
    assert demote_reader.status_code == 200
    assert demote_reader.json()["role_key"] == "member"

    # Now only 1 active super admin remains again; attempting to demote admin_user fails
    demote_again = client.patch(
        f"/api/v1/admin/users/{admin_user.id}",
        headers={"X-CSRF-Token": csrf_admin},
        json={"role_key": "member"}
    )
    assert demote_again.status_code == 400
    assert demote_again.json()["error"]["code"] == "CANNOT_DEMOTE_LAST_ADMIN"

def test_concurrent_demote_two_super_admins():
    """Simulates concurrent race condition where two requests attempt to demote two super admins simultaneously on separate DB sessions."""
    # Setup 2 active super admins
    setup_db = TestingSessionLocal()
    try:
        admin1 = setup_db.query(User).filter(User.username == "admin").first()
        reader = setup_db.query(User).filter(User.username == "reader").first()
        reader.role_key = "super_admin"
        reader.is_active = True
        admin1.role_key = "super_admin"
        admin1.is_active = True
        setup_db.commit()
        admin1_id = admin1.id
        reader_id = reader.id
    finally:
        setup_db.close()

    results = []

    def demote_task(target_id):
        thread_db = TestingSessionLocal()
        try:
            actor = thread_db.query(User).filter(User.username == "admin").first()
            admin_update_user(
                db=thread_db,
                user_id=target_id,
                role_key="member",
                is_active=None,
                actor=actor,
            )
            results.append((target_id, "SUCCESS"))
        except AppException as e:
            results.append((target_id, e.code))
        finally:
            thread_db.close()

    t1 = threading.Thread(target=demote_task, args=(admin1_id,))
    t2 = threading.Thread(target=demote_task, args=(reader_id,))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    outcomes = [r[1] for r in results]
    # Under correct row locking and advisory lock, exactly one demotion succeeds,
    # and the other is prevented by CANNOT_DEMOTE_LAST_ADMIN!
    assert "SUCCESS" in outcomes
    assert "CANNOT_DEMOTE_LAST_ADMIN" in outcomes

    # Verify at least one super admin is still active in DB
    verify_db = TestingSessionLocal()
    try:
        remaining_admins = verify_db.query(User).filter(User.role_key == "super_admin", User.is_active == True).count()
        assert remaining_admins >= 1
        # Cleanup: restore admin1 as super_admin, reader as member
        a1 = verify_db.query(User).filter(User.id == admin1_id).first()
        rd = verify_db.query(User).filter(User.id == reader_id).first()
        a1.role_key = "super_admin"
        a1.is_active = True
        rd.role_key = "member"
        rd.is_active = True
        verify_db.commit()
    finally:
        verify_db.close()


def test_r13_deactivating_user_blocks_immediately_and_prevents_resuscitation(db_session):
    """
    R13 / AUTH-02:
    Deactivating a user immediately blocks active sessions with 403 ACCOUNT_DISABLED,
    and re-enabling does not resuscitate pre-deactivation sessions.
    """
    from fastapi.testclient import TestClient
    from src.backend.main import app
    from src.backend.core.database import get_db

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        admin_client = TestClient(app, base_url="http://testserver")
        reader_client = TestClient(app, base_url="http://testserver")

        csrf_admin = auth_login(admin_client, "admin@folio.test")
        csrf_reader = auth_login(reader_client, "reader@folio.test")
        reader = db_session.query(User).filter(User.username == "reader").first()

        deact = admin_client.patch(
            f"/api/v1/admin/users/{reader.id}",
            headers={"X-CSRF-Token": csrf_admin},
            json={"is_active": False},
        )
        assert deact.status_code == 200

        blocked = reader_client.patch(
            "/api/v1/auth/profile",
            headers={"X-CSRF-Token": csrf_reader},
            json={"display_name": "Blocked"},
        )
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "ACCOUNT_DISABLED"

        react = admin_client.patch(
            f"/api/v1/admin/users/{reader.id}",
            headers={"X-CSRF-Token": csrf_admin},
            json={"is_active": True},
        )
        assert react.status_code == 200

        # Pre-deactivation session cannot be resuscitated after re-enable
        stale_res = reader_client.patch(
            "/api/v1/auth/profile",
            headers={"X-CSRF-Token": csrf_reader},
            json={"display_name": "Resuscitated"},
        )
        assert stale_res.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()
