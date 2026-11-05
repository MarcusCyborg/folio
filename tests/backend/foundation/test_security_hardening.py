import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from unittest.mock import patch

from src.backend.core.config import settings
from src.backend.core.security import hash_password, verify_password
from src.backend.core.session import create_session, get_session_by_token
from src.backend.core.rate_limit import rate_limiter
from src.backend.core.audit import redact_payload, redact_sensitive_text
from src.backend.main import app
from src.backend.core.database import get_db
from src.backend.models.auth import User
from scripts.bootstrap_admin import bootstrap_admin, validate_admin_password
from tests.conftest import TestingSessionLocal

@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Ensure rate limiter state is fresh before each test."""
    rate_limiter.reset()
    yield
    rate_limiter.reset()

def test_production_boot_fails_on_weak_secret():
    """Real app boot fails fast in production if APP_SECRET is weak or default."""
    original_env = settings.APP_ENV
    original_secret = settings.APP_SECRET
    original_cookie_secure = settings.COOKIE_SECURE
    try:
        settings.APP_ENV = "production"
        settings.COOKIE_SECURE = True
        settings.APP_SECRET = "folio_dev_insecure_default_secret_32_characters_long"

        # Real application boot via TestClient lifespan
        with pytest.raises(ValueError, match="APP_SECRET contains insecure or default pattern"):
            with TestClient(app):
                pass
    finally:
        settings.APP_ENV = original_env
        settings.APP_SECRET = original_secret
        settings.COOKIE_SECURE = original_cookie_secure

def test_production_boot_fails_on_insecure_cookie():
    """Real app boot fails fast in production if COOKIE_SECURE is False."""
    original_env = settings.APP_ENV
    original_secret = settings.APP_SECRET
    original_cookie_secure = settings.COOKIE_SECURE
    try:
        settings.APP_ENV = "production"
        settings.COOKIE_SECURE = False
        settings.APP_SECRET = "k9#mP$2vL@8xQ!zR5wY&1bN*7tC^4jF("

        with pytest.raises(ValueError, match="COOKIE_SECURE must be True in production environment"):
            with TestClient(app):
                pass
    finally:
        settings.APP_ENV = original_env
        settings.APP_SECRET = original_secret
        settings.COOKIE_SECURE = original_cookie_secure

def test_production_boot_fails_on_wildcard_cors(monkeypatch):
    """Real app boot fails fast in production if CORS origins contain wildcard '*'."""
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+psycopg://folio_prod_user:prod_pass_987@127.0.0.1:5432/folio_prod")
    original_env = settings.APP_ENV
    original_secret = settings.APP_SECRET
    original_cookie_secure = settings.COOKIE_SECURE
    original_cors = settings.CORS_ALLOWED_ORIGINS
    try:
        settings.APP_ENV = "production"
        settings.COOKIE_SECURE = True
        settings.APP_SECRET = "k9#mP$2vL@8xQ!zR5wY&1bN*7tC^4jF("
        settings.CORS_ALLOWED_ORIGINS = ["*", "https://folio.example.com"]

        with pytest.raises(ValueError, match="CORS_ALLOWED_ORIGINS cannot contain wildcard"):
            with TestClient(app):
                pass
    finally:
        settings.APP_ENV = original_env
        settings.APP_SECRET = original_secret
        settings.COOKIE_SECURE = original_cookie_secure
        settings.CORS_ALLOWED_ORIGINS = original_cors

def test_production_boot_succeeds_with_hardened_config():
    """Real app boot succeeds cleanly in production with compliant settings."""
    original_env = settings.APP_ENV
    original_secret = settings.APP_SECRET
    original_cookie_secure = settings.COOKIE_SECURE
    original_cors = settings.CORS_ALLOWED_ORIGINS
    original_db = settings.DATABASE_URL
    try:
        settings.APP_ENV = "production"
        settings.COOKIE_SECURE = True
        settings.APP_SECRET = "k9#mP$2vL@8xQ!zR5wY&1bN*7tC^4jF("
        settings.CORS_ALLOWED_ORIGINS = ["https://folio.example.com"]
        settings.DATABASE_URL = "postgresql+psycopg://folio_prod_user:prod_pass_987@127.0.0.1:5432/folio_prod"

        # Real boot execution
        with TestClient(app) as prod_client:
            res = prod_client.get("/health")
            assert res.status_code in (200, 503)
            if res.status_code == 503:
                assert res.json()["database"] == "unavailable"  # Zero information leak
    finally:
        settings.APP_ENV = original_env
        settings.APP_SECRET = original_secret
        settings.COOKIE_SECURE = original_cookie_secure
        settings.CORS_ALLOWED_ORIGINS = original_cors
        settings.DATABASE_URL = original_db

def test_cookie_security_flags_on_response(client):
    """When COOKIE_SECURE is True, Set-Cookie header contains Secure, HttpOnly, and SameSite."""
    original_cookie_secure = settings.COOKIE_SECURE
    try:
        settings.COOKIE_SECURE = True
        client.cookies.clear()
        res = client.get("/api/v1/auth/session")
        assert res.status_code == 200
        set_cookie = res.headers.get("set-cookie", "")
        assert "folio_session=" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "Secure" in set_cookie
        assert "samesite=lax" in set_cookie.lower()
    finally:
        settings.COOKIE_SECURE = original_cookie_secure

def test_origin_header_validation_cross_site_rejection(client):
    """Untrusted Origin header on POST request is rejected with 403 CSRF_FORBIDDEN."""
    sess_res = client.get("/api/v1/auth/session")
    csrf_token = sess_res.json()["csrf_token"]

    # Cross-origin attack with untrusted origin
    res_attack = client.post(
        "/api/v1/auth/register",
        headers={
            "X-CSRF-Token": csrf_token,
            "Origin": "https://malicious-attacker.com",
        },
        json={
            "email": "attack@folio.test",
            "username": "attackuser",
            "password": "Password1234!",
            "display_name": "Attacker",
        }
    )
    assert res_attack.status_code == 403
    assert res_attack.json()["error"]["code"] == "CSRF_FORBIDDEN"

    # Legitimate origin (http://testserver or configured origins)
    res_valid = client.post(
        "/api/v1/auth/register",
        headers={
            "X-CSRF-Token": csrf_token,
            "Origin": "http://testserver",
        },
        json={
            "email": "valid_user_orig@folio.test",
            "username": "valid_user_orig",
            "password": "Password1234!",
            "display_name": "Valid User",
        }
    )
    assert res_valid.status_code == 201

def test_login_rate_limiting_abuse(client):
    """Repeated failed login attempts trigger 429 TOO_MANY_REQUESTS."""
    sess_res = client.get("/api/v1/auth/session")
    csrf_token = sess_res.json()["csrf_token"]

    # Exceed maximum failed attempts (limit: 5)
    for attempt in range(settings.RATE_LIMIT_LOGIN_MAX_FAILED):
        res = client.post(
            "/api/v1/auth/login",
            headers={"X-CSRF-Token": csrf_token},
            json={"email": "victim@folio.test", "password": f"WrongPwd{attempt}!"}
        )
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"

    # Next attempt must be blocked by rate limiter
    res_blocked = client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": csrf_token},
        json={"email": "victim@folio.test", "password": "WrongPasswordAgain!"}
    )
    assert res_blocked.status_code == 429
    assert res_blocked.json()["error"]["code"] == "TOO_MANY_REQUESTS"

def test_registration_rate_limiting_abuse(client, db_session):
    """Repeated registration requests from the same IP trigger 429 TOO_MANY_REQUESTS."""
    sess_res = client.get("/api/v1/auth/session")
    csrf_token = sess_res.json()["csrf_token"]

    try:
        for i in range(settings.RATE_LIMIT_REGISTER_MAX):
            reg_res = client.post(
                "/api/v1/auth/register",
                headers={"X-CSRF-Token": csrf_token},
                json={
                    "email": f"flood_{i}@folio.test",
                    "username": f"flood_{i}",
                    "password": "Password1234!",
                    "display_name": f"User {i}",
                }
            )
            assert reg_res.status_code == 201
            csrf_token = reg_res.json()["csrf_token"]

        # Next attempt exceeds limit
        res_limit = client.post(
            "/api/v1/auth/register",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "email": "flood_overflow@folio.test",
                "username": "flood_overflow",
                "password": "Password1234!",
                "display_name": "Flood Overflow",
            }
        )
        assert res_limit.status_code == 429
        assert res_limit.json()["error"]["code"] == "TOO_MANY_REQUESTS"
    finally:
        # Cleanup registered test accounts
        floods = db_session.query(User).filter(User.username.like("flood_%")).all()
        for u in floods:
            db_session.delete(u)
        db_session.flush()

def test_admin_bootstrap_cli_creation_and_rotation(db_session):
    """Admin bootstrap CLI creates super admin, rotates password, revokes sessions, and protects passwords."""
    test_email = "bootstrap_admin_test@folio.test"
    test_user = "boot_admin_test"
    initial_pwd = "InitialStrongAdminPassword2026!"
    rotated_pwd = "RotatedStrongAdminPassword2026!"

    try:
        # Clean up any pre-existing user with this test email
        existing = db_session.query(User).filter(User.username == test_user).first()
        if existing:
            db_session.delete(existing)
            db_session.flush()

        # 1. Provision new admin
        admin = bootstrap_admin(
            email=test_email,
            username=test_user,
            password=initial_pwd,
            display_name="Bootstrap Admin",
            rotate=False,
            db=db_session,
            commit=False,
        )
        assert admin.id is not None
        assert admin.role_key == "super_admin"
        assert admin.is_active is True
        assert verify_password(initial_pwd, admin.password_hash)

        # 2. Attempting to provision existing user without --rotate raises ValueError
        with pytest.raises(ValueError, match="already exists. Specify --rotate"):
            bootstrap_admin(
                email=test_email,
                username=test_user,
                password=rotated_pwd,
                rotate=False,
                db=db_session,
                commit=False,
            )

        # 3. Create an active session for this admin
        sess_obj, raw_token = create_session(db_session, user=admin)
        db_session.flush()
        assert get_session_by_token(db_session, raw_token) is not None

        # 4. Rotate credentials with rotate=True
        rotated_admin = bootstrap_admin(
            email=test_email,
            username=test_user,
            password=rotated_pwd,
            rotate=True,
            db=db_session,
            commit=False,
        )
        assert verify_password(rotated_pwd, rotated_admin.password_hash)
        assert not verify_password(initial_pwd, rotated_admin.password_hash)

        # 5. Verify old session was revoked upon password rotation
        assert get_session_by_token(db_session, raw_token) is None

    finally:
        # Cleanup
        to_clean = db_session.query(User).filter(User.username == test_user).first()
        if to_clean:
            db_session.delete(to_clean)
            db_session.flush()

def test_secret_redaction_in_audit_and_text():
    """Sensitive keys, connection strings, and tokens are redacted from logs and audits."""
    # Dict payload redaction
    payload = {
        "username": "scholar",
        "password": "SecretPassword123!",
        "token": "secret_session_token_xyz",
        "APP_SECRET": "critical_app_secret_here",
        "database_url": "postgresql+psycopg://dbuser:SuperSecretPass@127.0.0.1:5432/folio_prod",
        "nested": {
            "csrf_token": "csrf_token_abc_123",
            "safe_field": "visible_content",
        }
    }
    redacted = redact_payload(payload)
    assert redacted["username"] == "scholar"
    assert redacted["password"] == "[REDACTED]"
    assert redacted["token"] == "[REDACTED]"
    assert redacted["APP_SECRET"] == "[REDACTED]"
    assert redacted["database_url"] == "[REDACTED]"
    assert redacted["nested"]["csrf_token"] == "[REDACTED]"
    assert redacted["nested"]["safe_field"] == "visible_content"

    # Raw text / connection string regex redaction
    err_text = "Failed to connect: postgresql+psycopg://dbuser:SecretPass123@db.internal:5432/prod_db timeout"
    safe_text = redact_sensitive_text(err_text)
    assert "SecretPass123" not in safe_text
    assert "[REDACTED_USER]:[REDACTED_PASSWORD]@db.internal:5432/prod_db" in safe_text

def test_security_headers_present(client):
    """Security headers (CSP, X-Content-Type-Options, X-Frame-Options, etc.) are present on all responses."""
    res = client.get("/health")
    assert res.status_code == 200
    headers = res.headers

    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in headers
    csp = headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert "frame-ancestors 'none'" in csp

def test_production_error_zero_leak(monkeypatch):
    """In production, unhandled 500 exceptions do not leak stack traces or exception details."""
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+psycopg://folio_prod_user:prod_pass_987@127.0.0.1:5432/folio_prod")
    original_env = settings.APP_ENV
    original_secret = settings.APP_SECRET
    original_cookie_secure = settings.COOKIE_SECURE
    original_overrides = app.dependency_overrides.copy()
    try:
        settings.APP_ENV = "production"
        settings.COOKIE_SECURE = True
        settings.APP_SECRET = "k9#mP$2vL@8xQ!zR5wY&1bN*7tC^4jF("

        def failing_get_db():
            raise Exception("psycopg.OperationalError: could not connect: postgresql://admin:leaked_pass@localhost:5432/folio")

        app.dependency_overrides[get_db] = failing_get_db
        with TestClient(app, base_url="http://testserver", raise_server_exceptions=False) as prod_client:
            res = prod_client.get("/health")
            assert res.status_code == 500
            data = res.json()
            assert data["error"]["code"] == "INTERNAL_SERVER_ERROR"
            assert data["error"]["message"] == "An unexpected internal server error occurred."
            assert "leaked_pass" not in str(data)
            assert "OperationalError" not in str(data)
    finally:
        settings.APP_ENV = original_env
        settings.APP_SECRET = original_secret
        settings.COOKIE_SECURE = original_cookie_secure
        app.dependency_overrides = original_overrides
