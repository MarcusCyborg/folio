import contextlib
import io
import json
import os
from pathlib import Path
import secrets
import sys

repo = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(repo))
sys.dont_write_bytecode = True
os.environ.update(APP_ENV="test", APP_SECRET=secrets.token_urlsafe(48),
    COOKIE_SECURE="false", ENABLE_LEGACY_SEARCH="false", PYTHON_DOTENV_DISABLED="1",
    DATABASE_URL="postgresql+psycopg://review@127.0.0.1:1/review_unused?connect_timeout=1",
    TEST_DATABASE_URL="postgresql+psycopg://review@127.0.0.1:1/review_ia_test?connect_timeout=1",
    CORS_ALLOWED_ORIGINS="http://testserver")
from fastapi.testclient import TestClient
from src.backend.main import app
from src.backend.core.config import settings

results = {"repo": str(repo), "boot": []}
for label, changes in [
    ("production_valid", {}),
    ("production_insecure_cookie", {"COOKIE_SECURE": False}),
    ("production_weak_secret", {"APP_SECRET": "short"}),
    ("production_wildcard_origin", {"CORS_ALLOWED_ORIGINS": ["*"]}),
    ("invalid_environment", {"APP_ENV": "typo-production"}),
]:
    settings.APP_ENV = "production"
    settings.COOKIE_SECURE = True
    settings.APP_SECRET = secrets.token_urlsafe(48)
    settings.CORS_ALLOWED_ORIGINS = ["https://folio.example.com"]
    for key, value in changes.items():
        setattr(settings, key, value)
    try:
        with TestClient(app) as client:
            response = client.get("/search?q=review")
            results["boot"].append({"case": label, "started": True, "legacy_status": response.status_code})
    except Exception as exc:
        results["boot"].append({"case": label, "started": False, "error_type": type(exc).__name__})

settings.APP_ENV = "production"
settings.COOKIE_SECURE = True
settings.APP_SECRET = secrets.token_urlsafe(48)
settings.CORS_ALLOWED_ORIGINS = ["https://folio.example.com"]
with TestClient(app, raise_server_exceptions=False) as client:
    response = client.get("/health")
    results["health_database_unavailable"] = {
        "status": response.status_code,
        "internal_error_exposed": "127.0.0.1" in response.text or "OperationalError" in response.text,
    }

from src.backend.core.database import get_db
class FaultingDatabase:
    def execute(self, *args, **kwargs):
        raise RuntimeError("REVIEW_INTERNAL_ERROR_SENTINEL")
def failing_db():
    yield FaultingDatabase()
app.dependency_overrides[get_db] = failing_db
with TestClient(app, raise_server_exceptions=False) as client:
    response = client.get("/health")
    results["health_fault_injection"] = {
        "status": response.status_code,
        "internal_error_exposed": "REVIEW_INTERNAL_ERROR_SENTINEL" in response.text,
    }
app.dependency_overrides.clear()

if (repo / "scripts/bootstrap_admin.py").exists():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from src.backend.models import Base
    from src.backend.models.auth import User
    from src.backend.core.security import hash_password, verify_password
    from src.backend.core.session import create_session, get_session_by_token
    from scripts.bootstrap_admin import bootstrap_admin
    # SQLite isolates a specific CLI business-logic probe; it does not certify PostgreSQL migrations.
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    output = io.StringIO()
    pwd = secrets.token_urlsafe(30)
    pwd2 = secrets.token_urlsafe(30)
    with Session(engine, expire_on_commit=False) as db, contextlib.redirect_stdout(output):
        admin = bootstrap_admin("review@invalid.example", "review_admin", pwd, db=db)
        initial_id = admin.id
        results["bootstrap"] = {"first_create": admin.role_key, "password_hash_verified": verify_password(pwd, admin.password_hash)}
        try:
            bootstrap_admin("review@invalid.example", "review_admin", pwd, db=db)
            results["bootstrap"]["duplicate_rejected"] = False
        except ValueError:
            results["bootstrap"]["duplicate_rejected"] = True
        session, token = create_session(db, user=admin)
        db.commit()
        rotated = bootstrap_admin("review@invalid.example", "review_admin", pwd2, rotate=True, db=db)
        results["bootstrap"]["rotation_preserves_id"] = rotated.id == initial_id
        results["bootstrap"]["old_session_revoked"] = get_session_by_token(db, token) is None
        member = User(email="member@invalid.example", username="existing_member", display_name="Review", password_hash=hash_password(pwd), role_key="member", is_active=True)
        db.add(member)
        db.commit()
        member_id = member.id
        promoted = bootstrap_admin("different@invalid.example", "existing_member", pwd2, rotate=True, db=db)
        results["bootstrap"]["mismatched_email_rotation"] = {
            "targeted_existing_member": promoted.id == member_id,
            "role_after": promoted.role_key,
            "email_matches_requested": promoted.email == "different@invalid.example",
        }
        results["bootstrap"]["password_in_output"] = pwd in output.getvalue() or pwd2 in output.getvalue()
    engine.dispose()
else:
    results["bootstrap"] = {"available": False}

print(json.dumps(results, indent=2))
