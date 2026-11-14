"""
test_bootstrap_security.py - Comprehensive Folio Bootstrap & Identity Security Tests.

Verifies remediation of Finding IA-03:
1. Normalization & Identity Disambiguation:
   - Both email and username after normalize must point to the EXACT SAME single super_admin.
   - Partial match (mismatch either way) is strictly rejected with IdentityMismatchError.
   - Two-account collision (email belongs to User A, username to User B) is rejected with IdentityCollisionError.
   - Member / non-admin accounts cannot be rotated or promoted (NonAdminRotationError).
   - Inactive / disabled accounts cannot be rotated or silently reactivated (InactiveAccountRotationError).
   - Non-existent accounts cannot be rotated (TargetAccountNotFoundError).
2. Safe Duplicate Handling:
   - Duplicate create without --rotate raises AccountAlreadyExistsError (CLI exit code 2).
   - Existing accounts are never mutated on duplicate rejection.
3. Transactional Integrity & State Snapshots:
   - Rotation preserves account ID and role_key ('super_admin').
   - Password hash is updated; active sessions are revoked.
   - Audit trail is written within the same transaction.
   - Rejections cause zero mutation, zero partial state change, and zero success audit logs.
4. Password Security:
   - Enforces password entropy, minimum length, and rejects demo/dictionary defaults.
   - Password is never logged or exposed in CLI output.

NOTE ON SQLITE USAGE IN THIS MODULE:
In-memory SQLite is used here solely to test the pure Python identity disambiguation logic,
transactional rollback, and state snapshots without external network dependencies.
Per Folio engineering invariants, SQLite is NOT treated as a certification for PostgreSQL migrations.
Live PostgreSQL CLI lifecycle verification is executed in test_bootstrap_postgres_lifecycle.py.
"""

import os
import sys
import subprocess
from pathlib import Path
import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.models.base import Base
from src.backend.models.auth import User, Role, SessionModel
from src.backend.models.system import AuditLog
from src.backend.core.security import hash_password, verify_password
from src.backend.core.session import create_session, get_session_by_token
from scripts.bootstrap_admin import (
    bootstrap_admin,
    validate_admin_password,
    BootstrapError,
    AccountAlreadyExistsError,
    IdentityMismatchError,
    IdentityCollisionError,
    NonAdminRotationError,
    InactiveAccountRotationError,
    TargetAccountNotFoundError,
    WEAK_PASSWORDS,
)

STRONG_PWD_1 = "SuperSecureAdminPassword2026!#"
STRONG_PWD_2 = "RotatedSuperAdminPassword2026!$"


# ==============================================================================
# In-Memory DB Fixture for Pure Identity Logic & Snapshot Verification
# ==============================================================================

@pytest.fixture
def mem_db():
    """Isolated in-memory SQLite session for pure identity logic verification."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        # Pre-seed role taxonomy
        session.add(Role(key="super_admin", label="Super Administrator"))
        session.add(Role(key="member", label="Member"))
        session.commit()
        yield session
    engine.dispose()


def snapshot_user_state(db: Session, user_id: int):
    """Captures exact user record and related audit count for diffing."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    audit_count = db.query(AuditLog).filter(AuditLog.entity_id == user_id).count()
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "display_name": user.display_name,
        "password_hash": user.password_hash,
        "role_key": user.role_key,
        "is_active": user.is_active,
        "audit_count": audit_count,
    }


# ==============================================================================
# Password Validation Unit Tests
# ==============================================================================

class TestPasswordValidation:
    def test_password_empty_or_none(self):
        with pytest.raises(ValueError, match="required and cannot be empty"):
            validate_admin_password("", "production")
        with pytest.raises(ValueError, match="required and cannot be empty"):
            validate_admin_password(None, "production")

    def test_password_too_short(self):
        with pytest.raises(ValueError, match="at least 12 characters"):
            validate_admin_password("ShortPwd12!", "production")

    def test_password_weak_dictionary_defaults_rejected(self):
        for weak in ("foliodemo2026!", "password123456", "admin12345678", "changeme12345", "superadmin123"):
            with pytest.raises(ValueError, match="too weak or matches demo defaults|contains insecure"):
                validate_admin_password(weak, "production")

    def test_password_low_entropy_rejected(self):
        with pytest.raises(ValueError, match="insufficient character diversity"):
            validate_admin_password("aaaaaaaaaaaaa", "production")
        with pytest.raises(ValueError, match="insufficient character diversity"):
            validate_admin_password("ababababababab", "production")

    def test_password_strong_accepted(self):
        # Must not raise
        validate_admin_password(STRONG_PWD_1, "production")
        validate_admin_password(STRONG_PWD_2, "staging")
        validate_admin_password("ComplexTestAdminPassword!99#", "test")


# ==============================================================================
# Identity Disambiguation & Rotation Matrix Tests
# ==============================================================================

class TestIdentityDisambiguationAndRotation:
    def test_create_initial_admin_success(self, mem_db):
        admin = bootstrap_admin(
            email="admin@folio.local",
            username="folio_admin",
            password=STRONG_PWD_1,
            display_name="Primary Admin",
            rotate=False,
            db=mem_db,
            commit=True,
        )
        assert admin.id is not None
        assert admin.email == "admin@folio.local"
        assert admin.username == "folio_admin"
        assert admin.role_key == "super_admin"
        assert admin.is_active is True
        assert verify_password(STRONG_PWD_1, admin.password_hash)

        # Audit log written
        audit = mem_db.query(AuditLog).filter(AuditLog.entity_id == admin.id).first()
        assert audit is not None
        assert audit.action == "auth.admin_bootstrap_created"

    def test_duplicate_create_same_identity_raises_already_exists(self, mem_db):
        admin = bootstrap_admin(
            email="admin@folio.local",
            username="folio_admin",
            password=STRONG_PWD_1,
            db=mem_db,
            commit=True,
        )
        state_before = snapshot_user_state(mem_db, admin.id)

        # Rerun without rotate raises AccountAlreadyExistsError
        with pytest.raises(AccountAlreadyExistsError, match="already exists. Specify --rotate"):
            bootstrap_admin(
                email="admin@folio.local",
                username="folio_admin",
                password=STRONG_PWD_2,
                rotate=False,
                db=mem_db,
                commit=True,
            )

        # Verify state is completely unchanged
        state_after = snapshot_user_state(mem_db, admin.id)
        assert state_before == state_after
        assert verify_password(STRONG_PWD_1, admin.password_hash)

    def test_rotate_exact_matching_super_admin_success(self, mem_db):
        admin = bootstrap_admin(
            email="admin@folio.local",
            username="folio_admin",
            password=STRONG_PWD_1,
            db=mem_db,
            commit=True,
        )
        initial_id = admin.id

        # Create active session for admin
        sess, token = create_session(mem_db, user=admin)
        mem_db.commit()
        assert get_session_by_token(mem_db, token) is not None

        # Rotate credentials
        rotated = bootstrap_admin(
            email="admin@folio.local",
            username="folio_admin",
            password=STRONG_PWD_2,
            display_name="Updated Admin",
            rotate=True,
            db=mem_db,
            commit=True,
        )

        # Verification of preserved attributes and updated hash
        assert rotated.id == initial_id
        assert rotated.role_key == "super_admin"
        assert rotated.is_active is True
        assert rotated.display_name == "Updated Admin"
        assert verify_password(STRONG_PWD_2, rotated.password_hash)
        assert not verify_password(STRONG_PWD_1, rotated.password_hash)

        # Active session was revoked
        assert get_session_by_token(mem_db, token) is None

        # Rotation audit log written
        rot_audit = mem_db.query(AuditLog).filter(
            AuditLog.entity_id == initial_id,
            AuditLog.action == "auth.admin_bootstrap_rotated"
        ).first()
        assert rot_audit is not None
        assert rot_audit.after.get("sessions_revoked") == 1

    def test_rotate_email_mismatch_rejected_without_mutation(self, mem_db):
        """Operator enters correct username but mismatched email: MUST NOT ROTATE."""
        admin = bootstrap_admin(
            email="admin@folio.local",
            username="folio_admin",
            password=STRONG_PWD_1,
            db=mem_db,
            commit=True,
        )
        state_before = snapshot_user_state(mem_db, admin.id)

        with pytest.raises(IdentityMismatchError, match="Identity mismatch: username 'folio_admin' matches existing user"):
            bootstrap_admin(
                email="mismatched_email@folio.local",
                username="folio_admin",
                password=STRONG_PWD_2,
                rotate=True,
                db=mem_db,
                commit=True,
            )

        state_after = snapshot_user_state(mem_db, admin.id)
        assert state_before == state_after
        assert verify_password(STRONG_PWD_1, admin.password_hash)

    def test_rotate_username_mismatch_rejected_without_mutation(self, mem_db):
        """Operator enters correct email but mismatched username: MUST NOT ROTATE."""
        admin = bootstrap_admin(
            email="admin@folio.local",
            username="folio_admin",
            password=STRONG_PWD_1,
            db=mem_db,
            commit=True,
        )
        state_before = snapshot_user_state(mem_db, admin.id)

        with pytest.raises(IdentityMismatchError, match="Identity mismatch: email 'admin@folio.local' matches existing user"):
            bootstrap_admin(
                email="admin@folio.local",
                username="mismatched_username",
                password=STRONG_PWD_2,
                rotate=True,
                db=mem_db,
                commit=True,
            )

        state_after = snapshot_user_state(mem_db, admin.id)
        assert state_before == state_after
        assert verify_password(STRONG_PWD_1, admin.password_hash)

    def test_two_account_collision_rejected_without_mutation(self, mem_db):
        """Email points to User A, username points to User B: MUST NOT ROTATE OR CREATE."""
        user_a = User(
            email="alice@folio.local",
            username="alice_user",
            display_name="Alice User",
            password_hash=hash_password(STRONG_PWD_1),
            role_key="super_admin",
            is_active=True,
        )
        user_b = User(
            email="bob@folio.local",
            username="bob_user",
            display_name="Bob User",
            password_hash=hash_password(STRONG_PWD_1),
            role_key="super_admin",
            is_active=True,
        )
        mem_db.add_all([user_a, user_b])
        mem_db.commit()

        state_a_before = snapshot_user_state(mem_db, user_a.id)
        state_b_before = snapshot_user_state(mem_db, user_b.id)

        # Attempt rotate targeting alice's email and bob's username
        with pytest.raises(IdentityCollisionError, match="Identity collision: email 'alice@folio.local' belongs to user 'alice_user'"):
            bootstrap_admin(
                email="alice@folio.local",
                username="bob_user",
                password=STRONG_PWD_2,
                rotate=True,
                db=mem_db,
                commit=True,
            )

        # Attempt create targeting alice's email and bob's username
        with pytest.raises(IdentityCollisionError, match="Identity collision"):
            bootstrap_admin(
                email="alice@folio.local",
                username="bob_user",
                password=STRONG_PWD_2,
                rotate=False,
                db=mem_db,
                commit=True,
            )

        # Neither account was mutated
        assert snapshot_user_state(mem_db, user_a.id) == state_a_before
        assert snapshot_user_state(mem_db, user_b.id) == state_b_before

    def test_rotate_non_admin_member_rejected_no_promotion(self, mem_db):
        """Targeting existing member: MUST NOT ROTATE, MUST NOT PROMOTE (Finding IA-03 core)."""
        member = User(
            email="member@folio.local",
            username="existing_member",
            display_name="Existing Member",
            password_hash=hash_password(STRONG_PWD_1),
            role_key="member",
            is_active=True,
        )
        mem_db.add(member)
        mem_db.commit()

        state_before = snapshot_user_state(mem_db, member.id)

        # Rotate targeting matching email and username of member
        with pytest.raises(NonAdminRotationError, match="has role 'member'. Bootstrap rotate cannot promote non-super_admin accounts"):
            bootstrap_admin(
                email="member@folio.local",
                username="existing_member",
                password=STRONG_PWD_2,
                rotate=True,
                db=mem_db,
                commit=True,
            )

        # Rotate targeting mismatched email and member's username
        with pytest.raises(IdentityMismatchError):
            bootstrap_admin(
                email="random_admin@folio.local",
                username="existing_member",
                password=STRONG_PWD_2,
                rotate=True,
                db=mem_db,
                commit=True,
            )

        state_after = snapshot_user_state(mem_db, member.id)
        assert state_before == state_after
        assert member.role_key == "member"
        assert verify_password(STRONG_PWD_1, member.password_hash)

    def test_rotate_inactive_admin_rejected_no_reactivation(self, mem_db):
        """Disabled super_admin: MUST NOT ROTATE, MUST NOT REACTIVATE SILENTLY."""
        disabled_admin = User(
            email="disabled@folio.local",
            username="disabled_admin",
            display_name="Disabled Admin",
            password_hash=hash_password(STRONG_PWD_1),
            role_key="super_admin",
            is_active=False,
        )
        mem_db.add(disabled_admin)
        mem_db.commit()

        state_before = snapshot_user_state(mem_db, disabled_admin.id)

        with pytest.raises(InactiveAccountRotationError, match="is inactive/disabled. Bootstrap rotate cannot reactivate"):
            bootstrap_admin(
                email="disabled@folio.local",
                username="disabled_admin",
                password=STRONG_PWD_2,
                rotate=True,
                db=mem_db,
                commit=True,
            )

        state_after = snapshot_user_state(mem_db, disabled_admin.id)
        assert state_before == state_after
        assert disabled_admin.is_active is False
        assert verify_password(STRONG_PWD_1, disabled_admin.password_hash)

    def test_rotate_non_existent_target_rejected(self, mem_db):
        """Rotating an account that does not exist raises TargetAccountNotFoundError."""
        with pytest.raises(TargetAccountNotFoundError, match="does not exist. Cannot rotate"):
            bootstrap_admin(
                email="ghost@folio.local",
                username="ghost_admin",
                password=STRONG_PWD_1,
                rotate=True,
                db=mem_db,
                commit=True,
            )
        assert mem_db.query(User).count() == 0

    def test_duplicate_create_with_existing_email_only(self, mem_db):
        """Creating an account when email already exists raises AccountAlreadyExistsError."""
        bootstrap_admin("unique@folio.local", "user_one", STRONG_PWD_1, db=mem_db, commit=True)
        with pytest.raises(AccountAlreadyExistsError, match="email 'unique@folio.local' already exists"):
            bootstrap_admin("unique@folio.local", "user_two", STRONG_PWD_2, rotate=False, db=mem_db, commit=True)
        assert mem_db.query(User).count() == 1

    def test_duplicate_create_with_existing_username_only(self, mem_db):
        """Creating an account when username already exists raises AccountAlreadyExistsError."""
        bootstrap_admin("user_one@folio.local", "unique_name", STRONG_PWD_1, db=mem_db, commit=True)
        with pytest.raises(AccountAlreadyExistsError, match="username 'unique_name' already exists"):
            bootstrap_admin("user_two@folio.local", "unique_name", STRONG_PWD_2, rotate=False, db=mem_db, commit=True)
        assert mem_db.query(User).count() == 1

    def test_normalization_stripping_and_case_insensitivity(self, mem_db):
        """Email and username normalization ensures robust case-insensitive matching."""
        admin = bootstrap_admin(
            email="  Admin_Caps@Folio.Local  ",
            username="  SuperAdmin_Caps  ",
            password=STRONG_PWD_1,
            db=mem_db,
            commit=True,
        )
        assert admin.email == "admin_caps@folio.local"
        assert admin.username == "superadmin_caps"

        # Rotate with lowercase variations matches cleanly
        rotated = bootstrap_admin(
            email="admin_caps@folio.local",
            username="superadmin_caps",
            password=STRONG_PWD_2,
            rotate=True,
            db=mem_db,
            commit=True,
        )
        assert rotated.id == admin.id
        assert verify_password(STRONG_PWD_2, rotated.password_hash)


# ==============================================================================
# CLI Subprocess Execution Tests
# ==============================================================================

class TestCliSubprocessExecution:
    def test_cli_non_interactive_without_password_exits_code_1(self):
        """CLI without password in non-interactive environment exits with code 1."""
        env = os.environ.copy()
        env.pop("ADMIN_BOOTSTRAP_PASSWORD", None)

        proc = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "bootstrap_admin.py"), "--non-interactive"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert proc.returncode == 1
        assert "ERROR: Password required via ADMIN_BOOTSTRAP_PASSWORD" in proc.stderr

    def test_cli_passwords_never_leaked_in_output(self):
        """Passwords passed via env are never leaked in stdout or stderr on failure."""
        secret_pwd = "SecretMarkerSubstringThatMustNeverBePrinted123!"
        env = os.environ.copy()
        env["ADMIN_BOOTSTRAP_PASSWORD"] = secret_pwd
        env["ADMIN_BOOTSTRAP_EMAIL"] = "test_cli@folio.local"
        env["ADMIN_BOOTSTRAP_USERNAME"] = "test_cli"
        # Trigger failure using invalid database connection
        env["DATABASE_URL"] = "postgresql+psycopg://review:fake_pass@127.0.0.1:1/nonexistent?connect_timeout=1"

        proc = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "bootstrap_admin.py"), "--non-interactive"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert secret_pwd not in proc.stdout
        assert secret_pwd not in proc.stderr
        assert "fake_pass" not in proc.stdout
        assert "fake_pass" not in proc.stderr
