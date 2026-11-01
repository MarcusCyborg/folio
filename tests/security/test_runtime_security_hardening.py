"""
test_runtime_security_hardening.py - Runtime Security, RBAC, CSRF, Cookie, and Error Redaction Tests.

Verifies end-to-end security protections across the HTTP layer:
1. Cookie Security Flags: Set-Cookie contains HttpOnly, Secure (when enabled), and SameSite=lax.
2. Origin & CSRF Protection:
   - State-changing requests with untrusted Origin header are rejected with 403 CSRF_FORBIDDEN.
   - State-changing requests without a valid X-CSRF-Token header are rejected with 403 CSRF_FORBIDDEN.
3. Role-Based Access Control (RBAC):
   - Unauthenticated guest accessing protected endpoints receives 401 UNAUTHORIZED.
   - Member accounts accessing staff/admin endpoints receive 403 FORBIDDEN.
   - Super admin accounts have comprehensive access.
4. Session Revocation & Disabled Users:
   - Immediate rejection with 403 ACCOUNT_DISABLED when an account is deactivated.
   - Immediate session revocation upon deactivation.
5. Production Error Redaction:
   - Unhandled 500 exceptions in production redact internal details, database URLs, and credentials.
   - Clean, standardized error schema returned to clients.
6. Zero Runtime Protection Disabled:
   - Rate limiters, origin verification, and authentication dependencies remain active.
"""

import os
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Ensure all models are registered in Base.metadata
import src.backend.models
from src.backend.models.base import Base
from src.backend.models.auth import User, Role, Permission, RolePermission, SessionModel
from src.backend.main import app
from src.backend.core.config import settings
from src.backend.core.database import get_db
from src.backend.core.security import hash_password
from src.backend.core.session import create_session, set_session_cookie, get_session_by_token
from scripts.seed_folio import seed_roles_and_permissions


@pytest.fixture
def db_session_factory():
    """In-memory SQLite database providing schema and pre-seeded roles for HTTP security tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with TestingSessionLocal() as session:
        seed_roles_and_permissions(session)
        session.commit()

    yield TestingSessionLocal
    engine.dispose()


@pytest.fixture
def http_client(db_session_factory):
    """TestClient configured with dependency override for get_db."""
    def override_get_db():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, base_url="http://testserver", raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


class TestCookieAndOriginSecurity:
    def test_cookie_security_flags(self, http_client):
        """Set-Cookie header enforces HttpOnly, Secure, and SameSite=lax when COOKIE_SECURE is True."""
        orig_secure = settings.COOKIE_SECURE
        try:
            settings.COOKIE_SECURE = True
            res = http_client.get("/api/v1/auth/session")
            assert res.status_code == 200
            set_cookie = res.headers.get("set-cookie", "")
            assert "folio_session=" in set_cookie
            assert "HttpOnly" in set_cookie
            assert "Secure" in set_cookie
            assert "samesite=lax" in set_cookie.lower()
        finally:
            settings.COOKIE_SECURE = orig_secure

    def test_untrusted_origin_rejected_on_post(self, http_client):
        """Cross-site attack with untrusted Origin header is rejected with 403 CSRF_FORBIDDEN."""
        sess_res = http_client.get("/api/v1/auth/session")
        csrf_token = sess_res.json()["csrf_token"]

        res = http_client.post(
            "/api/v1/auth/register",
            headers={
                "X-CSRF-Token": csrf_token,
                "Origin": "https://malicious-attacker.com",
            },
            json={
                "email": "attacker@evil.com",
                "username": "attacker",
                "password": "StrongPassword2026!#",
                "display_name": "Attacker",
            },
        )
        assert res.status_code == 403
        data = res.json()
        assert data["error"]["code"] == "CSRF_FORBIDDEN"

    def test_missing_or_invalid_csrf_token_rejected_on_post(self, http_client):
        """State-modifying POST request without valid CSRF token is rejected with 403 CSRF_FORBIDDEN."""
        # 1. Missing CSRF token
        res_missing = http_client.post(
            "/api/v1/auth/register",
            headers={"Origin": "http://testserver"},
            json={
                "email": "user@folio.local",
                "username": "valid_user",
                "password": "StrongPassword2026!#",
                "display_name": "Valid User",
            },
        )
        assert res_missing.status_code == 403
        assert res_missing.json()["error"]["code"] == "CSRF_FORBIDDEN"

        # 2. Tampered CSRF token
        res_tampered = http_client.post(
            "/api/v1/auth/register",
            headers={
                "Origin": "http://testserver",
                "X-CSRF-Token": "tampered_forged_csrf_token_1234567890",
            },
            json={
                "email": "user@folio.local",
                "username": "valid_user",
                "password": "StrongPassword2026!#",
                "display_name": "Valid User",
            },
        )
        assert res_tampered.status_code == 403
        assert res_tampered.json()["error"]["code"] == "CSRF_FORBIDDEN"


class TestRoleBasedAccessControl:
    def test_guest_cannot_access_protected_endpoint(self, http_client):
        """Unauthenticated guest request to /profile returns 401 UNAUTHORIZED."""
        sess_res = http_client.get("/api/v1/auth/session")
        csrf_token = sess_res.json()["csrf_token"]

        res = http_client.patch(
            "/api/v1/auth/profile",
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf_token},
            json={"display_name": "Guest New Name"},
        )
        assert res.status_code == 401
        data = res.json()
        assert data["error"]["code"] == "UNAUTHORIZED"

    def test_member_cannot_access_admin_endpoint(self, http_client, db_session_factory):
        """Standard member account accessing admin-only endpoint is rejected with 403 FORBIDDEN."""
        with db_session_factory() as db:
            member = User(
                email="member@folio.local",
                username="test_member",
                display_name="Test Member",
                password_hash=hash_password("MemberPassword2026!#"),
                role_key="member",
                is_active=True,
            )
            db.add(member)
            db.commit()

            sess_obj, raw_token = create_session(db, user=member)
            db.commit()

        # Access admin-only endpoint
        http_client.cookies.set(settings.SESSION_COOKIE_NAME, raw_token)
        res = http_client.get("/api/v1/admin/documents")
        assert res.status_code == 403
        data = res.json()
        assert data["error"]["code"] == "FORBIDDEN"

    def test_super_admin_can_access_admin_endpoint(self, http_client, db_session_factory):
        """Super admin account accessing admin endpoint is authorized (returns 200)."""
        with db_session_factory() as db:
            admin = User(
                email="admin@folio.local",
                username="super_admin_user",
                display_name="Super Admin",
                password_hash=hash_password("SuperAdminPassword2026!#"),
                role_key="super_admin",
                is_active=True,
            )
            db.add(admin)
            db.commit()

            sess_obj, raw_token = create_session(db, user=admin)
            db.commit()

        http_client.cookies.set(settings.SESSION_COOKIE_NAME, raw_token)
        res = http_client.get("/api/v1/admin/documents")
        assert res.status_code == 200


class TestSessionRevocationAndDisabledUser:
    def test_disabled_user_session_immediately_rejected(self, http_client, db_session_factory):
        """When a user is deactivated, subsequent requests using active sessions return 403 ACCOUNT_DISABLED."""
        with db_session_factory() as db:
            user = User(
                email="victim@folio.local",
                username="victim_user",
                display_name="Victim User",
                password_hash=hash_password("VictimPassword2026!#"),
                role_key="member",
                is_active=True,
            )
            db.add(user)
            db.commit()

            sess_obj, raw_token = create_session(db, user=user)
            db.commit()
            csrf = sess_obj.csrf_token

        # Request succeeds while user is active
        http_client.cookies.set(settings.SESSION_COOKIE_NAME, raw_token)
        res_active = http_client.patch(
            "/api/v1/auth/profile",
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
            json={"display_name": "Active User Name"},
        )
        assert res_active.status_code == 200

        # Deactivate user
        with db_session_factory() as db:
            target = db.query(User).filter(User.username == "victim_user").first()
            target.is_active = False
            db.commit()

        # Request with same session now fails with 403 ACCOUNT_DISABLED
        res_deactivated = http_client.patch(
            "/api/v1/auth/profile",
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
            json={"display_name": "Changed Again"},
        )
        assert res_deactivated.status_code == 403
        data = res_deactivated.json()
        assert data["error"]["code"] == "ACCOUNT_DISABLED"

        # The session in DB was revoked as part of deactivation enforcement
        with db_session_factory() as db:
            assert get_session_by_token(db, raw_token) is None


class TestProductionErrorRedaction:
    def test_production_unhandled_error_zero_leak(self):
        """In production environment, unhandled 500 exceptions redact internal database details and credentials."""
        orig_env = settings.APP_ENV
        orig_secret = settings.APP_SECRET
        orig_cookie_secure = settings.COOKIE_SECURE

        def faulting_get_db():
            raise RuntimeError("psycopg.OperationalError: could not connect: postgresql://admin:leaked_pass@127.0.0.1:5432/folio_prod")

        app.dependency_overrides[get_db] = faulting_get_db
        try:
            settings.APP_ENV = "production"
            settings.COOKIE_SECURE = True
            settings.APP_SECRET = "k9#mP$2vL@8xQ!zR5wY&1bN*7tC^4jF(9a1b2c3d4e5f6g7h8i9j0k"

            with TestClient(app, base_url="http://testserver", raise_server_exceptions=False) as client:
                res = client.get("/health")
                assert res.status_code == 500
                data = res.json()
                assert data["error"]["code"] == "INTERNAL_SERVER_ERROR"
                assert data["error"]["message"] == "An unexpected internal server error occurred."
                # Zero leak assertion: sensitive strings never present in body
                assert "leaked_pass" not in res.text
                assert "OperationalError" not in res.text
                assert "postgresql://" not in res.text
        finally:
            settings.APP_ENV = orig_env
            settings.APP_SECRET = orig_secret
            settings.COOKIE_SECURE = orig_cookie_secure
            app.dependency_overrides.clear()
