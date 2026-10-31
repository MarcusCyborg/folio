import pytest
from src.backend.models.auth import User
from src.backend.core.security import hash_password

def test_guest_session_creation(client):
    """GET /api/v1/auth/session should create a guest session and return csrf_token."""
    res = client.get("/api/v1/auth/session")
    assert res.status_code == 200
    data = res.json()
    assert data["user"] is None
    assert "csrf_token" in data
    assert len(data["csrf_token"]) > 20
    assert "folio_session" in client.cookies

def test_csrf_token_enforcement(client):
    """POST requests without valid X-CSRF-Token must be rejected with 403."""
    # First get session to receive cookies and csrf_token
    sess_res = client.get("/api/v1/auth/session")
    csrf_token = sess_res.json()["csrf_token"]

    # Try POST without CSRF header
    res_no_csrf = client.post(
        "/api/v1/auth/register",
        json={"email": "newuser@test.local", "username": "newuser", "password": "Password1234!", "display_name": "New User"}
    )
    assert res_no_csrf.status_code == 403
    assert res_no_csrf.json()["error"]["code"] == "CSRF_FORBIDDEN"

    # Try POST with wrong CSRF header
    res_wrong_csrf = client.post(
        "/api/v1/auth/register",
        headers={"X-CSRF-Token": "invalid_csrf_token_string_here"},
        json={"email": "newuser@test.local", "username": "newuser", "password": "Password1234!", "display_name": "New User"}
    )
    assert res_wrong_csrf.status_code == 403

def test_registration_and_no_role_escalation(client, db_session):
    """Registering creates a member. Attempting to specify an elevated role must be ignored."""
    sess_res = client.get("/api/v1/auth/session")
    csrf_token = sess_res.json()["csrf_token"]

    res = client.post(
        "/api/v1/auth/register",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "email": "scholar@folio.test",
            "username": "scholar",
            "password": "ValidPassword1234!",
            "display_name": "Dr. Scholar",
            "role_key": "super_admin",  # Attacker attempt to escalate
        }
    )
    assert res.status_code == 201
    data = res.json()
    assert data["user"]["email"] == "scholar@folio.test"
    assert data["user"]["username"] == "scholar"
    assert data["user"]["role_key"] == "member"  # Forced to member!
    assert "documents:write" not in data["user"]["permissions"]

def test_login_success_and_session_rotation(client, db_session):
    """Successful login returns user info and rotates session/CSRF."""
    sess_res = client.get("/api/v1/auth/session")
    initial_csrf = sess_res.json()["csrf_token"]
    initial_cookie = client.cookies.get("folio_session")

    res = client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": initial_csrf},
        json={"email": "admin@folio.test", "password": "FolioDemo2026!"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["user"]["role_key"] == "super_admin"
    assert data["user"]["username"] == "admin"
    assert "users:manage" in data["user"]["permissions"]
    assert "documents:write" in data["user"]["permissions"]

    new_csrf = data["csrf_token"]
    assert new_csrf != initial_csrf  # CSRF rotated
    new_cookie = client.cookies.get("folio_session")
    assert new_cookie != initial_cookie  # Session cookie rotated

def test_login_invalid_credentials(client):
    """Invalid password returns generic 401."""
    sess_res = client.get("/api/v1/auth/session")
    csrf_token = sess_res.json()["csrf_token"]

    res = client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": csrf_token},
        json={"email": "admin@folio.test", "password": "WrongPassword999!"}
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"

def test_disabled_user_access_blocked(client, db_session):
    """Deactivated user account cannot log in or perform authenticated actions."""
    # Create deactivated user directly
    user = User(
        email="banned@folio.test",
        username="banned_user",
        display_name="Banned",
        password_hash=hash_password("Password1234!"),
        role_key="member",
        is_active=False
    )
    db_session.add(user)
    db_session.flush()

    sess_res = client.get("/api/v1/auth/session")
    csrf = sess_res.json()["csrf_token"]

    res = client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": csrf},
        json={"email": "banned@folio.test", "password": "Password1234!"}
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "ACCOUNT_DISABLED"

def test_profile_update_and_password_change(client):
    """User can update profile and change password, revoking old sessions."""
    # Login as reader
    sess_res = client.get("/api/v1/auth/session")
    csrf = sess_res.json()["csrf_token"]

    login_res = client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": csrf},
        json={"email": "reader@folio.test", "password": "FolioDemo2026!"}
    )
    assert login_res.status_code == 200
    csrf = login_res.json()["csrf_token"]

    # Update profile
    prof_res = client.patch(
        "/api/v1/auth/profile",
        headers={"X-CSRF-Token": csrf},
        json={"display_name": "Updated Scholar", "bio": "Machine learning researcher"}
    )
    assert prof_res.status_code == 200
    assert prof_res.json()["display_name"] == "Updated Scholar"
    assert prof_res.json()["bio"] == "Machine learning researcher"

    # Change password
    pwd_res = client.post(
        "/api/v1/auth/password",
        headers={"X-CSRF-Token": csrf},
        json={"current_password": "FolioDemo2026!", "new_password": "NewSecretPassword2026!"}
    )
    assert pwd_res.status_code == 200
    new_csrf = pwd_res.json()["csrf_token"]

    # Logout
    logout_res = client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": new_csrf}
    )
    assert logout_res.status_code == 200
    assert logout_res.json()["user"] is None
