#!/usr/bin/env python3
"""
Folio Initial Admin Provisioning & Rotation CLI.

Safely provisions or rotates the primary super_admin credentials without hardcoding
or logging credentials. Compatible with interactive terminal (hidden password prompt)
and automated container/CI deployment via environment variables.

Remediation Finding IA-03:
- Normalization: email and username are stripped and lowercased.
- Identity Disambiguation:
  * When creating (rotate=False): both email and username must be unused.
    If an account with the same email and username exists, raises AccountAlreadyExistsError (exit code 2).
    If an account with matching email exists but different username (or vice versa),
    or if two different accounts collide, raises AccountAlreadyExistsError / IdentityCollisionError.
    Never mutates any existing account during create.
  * When rotating (rotate=True): both email AND username after normalize must point to
    the EXACT SAME existing super_admin account.
    - If neither exists: raises TargetAccountNotFoundError.
    - If one matches but other does not: raises IdentityMismatchError.
    - If email matches user A and username matches user B: raises IdentityCollisionError.
    - If matched user is not a super_admin: raises NonAdminRotationError (no silent promotion).
    - If matched user is inactive: raises InactiveAccountRotationError (no silent reactivation).
  * On rotation success: preserves ID and role, updates password hash, revokes all active
    sessions, and writes audit record within the same transaction.
  * On rejection: zero partial mutation, zero success audit record.

Operational Policy:
- Emergency Recovery Policy: Inactive/disabled super_admin accounts or orphaned systems
  cannot be reactivated via bootstrap_admin.py --rotate. Account reactivation requires
  a separate operational recovery procedure with verified operator identity checks,
  multi-party approval, and audit review.
- Password Security: Credentials must be supplied via ADMIN_BOOTSTRAP_PASSWORD or
  secure interactive prompt (getpass). CLI argument --password is deprecated and discouraged.
"""

import sys
import os
import argparse
import getpass
import warnings
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import func

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.core.config import settings
from src.backend.core.database import SessionLocal
from src.backend.core.security import hash_password
from src.backend.core.session import revoke_user_sessions
from src.backend.core.audit import write_audit
from src.backend.models.auth import User
from scripts.seed_folio import seed_roles_and_permissions, seed_settings

WEAK_PASSWORDS = {
    "foliodemo2026!",
    "password",
    "password123",
    "admin123",
    "changeme",
    "superadmin",
    "12345678",
    "123456789012",
}


# ==============================================================================
# Semantic Bootstrap Exceptions (Subclasses of ValueError for backward compat)
# ==============================================================================

class BootstrapError(ValueError):
    """Base error for bootstrap operations."""
    pass


class AccountAlreadyExistsError(BootstrapError):
    """Raised when account already exists and rotate is not specified."""
    pass


class IdentityMismatchError(BootstrapError):
    """Raised when email and username do not match the same account."""
    pass


class IdentityCollisionError(BootstrapError):
    """Raised when email and username belong to two different accounts."""
    pass


class NonAdminRotationError(BootstrapError):
    """Raised when rotate targets a non-super_admin account."""
    pass


class InactiveAccountRotationError(BootstrapError):
    """Raised when rotate targets an inactive/disabled account."""
    pass


class TargetAccountNotFoundError(BootstrapError):
    """Raised when rotate targets an account that does not exist."""
    pass


# ==============================================================================
# Password Validation
# ==============================================================================

def validate_admin_password(password: str, env: str = "production") -> None:
    """
    Validates super_admin password strength and complexity.
    Rejects short passwords, weak dictionary defaults, and low entropy.
    """
    if not password:
        raise ValueError("Admin password is required and cannot be empty.")
    if len(password) < 12:
        raise ValueError("Admin password must be at least 12 characters long.")
    pwd_lower = password.lower()
    if pwd_lower in WEAK_PASSWORDS:
        raise ValueError(f"Admin password is too weak or matches demo defaults for {env}.")
    trivial_starts = ("password", "foliodemo", "changeme", "admin123", "12345678", "superadmin123")
    if any(pwd_lower == t or pwd_lower.startswith(t) for t in trivial_starts):
        raise ValueError(f"Admin password contains insecure or default pattern for {env}.")
    if len(set(password)) < 6:
        raise ValueError("Admin password has insufficient character diversity/entropy.")


# ==============================================================================
# Core Bootstrap Function
# ==============================================================================

def bootstrap_admin(
    email: str,
    username: str,
    password: str,
    display_name: str = "Super Administrator",
    rotate: bool = False,
    db: Session = None,
    commit: bool = True,
) -> User:
    """
    Provisions a new Super Admin or rotates credentials of an existing Super Admin.
    Guarantees no plain text passwords are logged.
    """
    if not email or not email.strip():
        raise ValueError("Admin email is required and cannot be empty.")
    if not username or not username.strip():
        raise ValueError("Admin username is required and cannot be empty.")

    should_close_db = False
    if db is None:
        db = SessionLocal()
        should_close_db = True

    try:
        validate_admin_password(password, settings.APP_ENV)

        # Ensure base taxonomy, roles, and permissions exist if not yet provisioned
        from src.backend.models.auth import Role
        if not db.query(Role).filter(Role.key == "super_admin").first():
            seed_roles_and_permissions(db)
            seed_settings(db)

        norm_email = email.strip().lower()
        norm_username = username.strip().lower()

        user_by_email = db.query(User).filter(func.lower(User.email) == norm_email).first()
        user_by_username = db.query(User).filter(func.lower(User.username) == norm_username).first()

        # Case 1: Two distinct accounts collide on the requested identifiers
        if user_by_email is not None and user_by_username is not None and user_by_email.id != user_by_username.id:
            raise IdentityCollisionError(
                f"Identity collision: email '{norm_email}' belongs to user '{user_by_email.username}' "
                f"(id={user_by_email.id}), while username '{norm_username}' belongs to user "
                f"'{user_by_username.username}' (id={user_by_username.id})."
            )

        # Case 2: Exactly one of the identifiers matches an existing account (partial match)
        if (user_by_email is not None and user_by_username is None) or (user_by_email is None and user_by_username is not None):
            existing = user_by_email or user_by_username
            matched_field = "email" if user_by_email is not None else "username"
            matched_val = norm_email if user_by_email is not None else norm_username
            if rotate:
                raise IdentityMismatchError(
                    f"Identity mismatch: {matched_field} '{matched_val}' matches existing user "
                    f"'{existing.username}', but the other identifier does not match. "
                    f"Bootstrap rotate requires both email and username to identify the same existing super_admin."
                )
            else:
                raise AccountAlreadyExistsError(
                    f"An account with {matched_field} '{matched_val}' already exists. "
                    f"Cannot provision duplicate user."
                )

        # Case 3: Both email and username point to the exact same existing account
        if user_by_email is not None and user_by_username is not None and user_by_email.id == user_by_username.id:
            target_user = user_by_email
            if not rotate:
                raise AccountAlreadyExistsError(
                    f"User '{target_user.username}' ({target_user.email}) already exists. "
                    f"Specify --rotate to update password."
                )

            # Check role: rotate MUST NOT silently promote non-admin accounts
            if target_user.role_key != "super_admin":
                raise NonAdminRotationError(
                    f"Target account '{target_user.username}' has role '{target_user.role_key}'. "
                    f"Bootstrap rotate cannot promote non-super_admin accounts to super_admin."
                )

            # Check active: rotate MUST NOT silently reactivate inactive accounts
            if not target_user.is_active:
                raise InactiveAccountRotationError(
                    f"Target account '{target_user.username}' is inactive/disabled. "
                    f"Bootstrap rotate cannot reactivate disabled accounts. "
                    f"Account recovery requires dedicated administrative intervention."
                )

            # Rotate credentials while strictly preserving ID and super_admin role
            before_state = {
                "role_key": target_user.role_key,
                "is_active": target_user.is_active,
            }
            target_user.password_hash = hash_password(password)
            if display_name:
                target_user.display_name = display_name

            # Revoke all active sessions of this admin on rotation
            revoked_count = revoke_user_sessions(db, target_user.id)

            write_audit(
                db=db,
                actor=target_user,
                action="auth.admin_bootstrap_rotated",
                entity_type="user",
                entity_id=target_user.id,
                before=before_state,
                after={"role_key": "super_admin", "is_active": True, "sessions_revoked": revoked_count},
            )
            if commit:
                db.commit()
            else:
                db.flush()
            print(f"[SUCCESS] Admin account '{target_user.username}' ({target_user.email}) password rotated. Revoked {revoked_count} active sessions.")
            return target_user

        # Case 4: Neither identifier exists
        if rotate:
            raise TargetAccountNotFoundError(
                f"Target super_admin account with email '{norm_email}' and username '{norm_username}' does not exist. "
                f"Cannot rotate credentials of a non-existent account."
            )

        # Create new initial Super Admin
        new_admin = User(
            email=norm_email,
            username=norm_username,
            display_name=display_name or "Super Administrator",
            password_hash=hash_password(password),
            role_key="super_admin",
            is_active=True,
        )
        db.add(new_admin)
        db.flush()

        write_audit(
            db=db,
            actor=new_admin,
            action="auth.admin_bootstrap_created",
            entity_type="user",
            entity_id=new_admin.id,
            before=None,
            after={"username": new_admin.username, "role_key": "super_admin"},
        )
        if commit:
            db.commit()
        else:
            db.flush()
        print(f"[SUCCESS] Initial Super Admin account '{new_admin.username}' ({new_admin.email}) provisioned successfully.")
        return new_admin

    except Exception:
        if commit:
            db.rollback()
        raise
    finally:
        if should_close_db:
            db.close()


# ==============================================================================
# CLI Entry Point
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="Folio Admin Bootstrap & Rotation CLI")
    parser.add_argument("--email", default=os.getenv("ADMIN_BOOTSTRAP_EMAIL", "admin@folio.local"), help="Admin email address")
    parser.add_argument("--username", default=os.getenv("ADMIN_BOOTSTRAP_USERNAME", "admin"), help="Admin username")
    parser.add_argument("--display-name", default=os.getenv("ADMIN_BOOTSTRAP_DISPLAY_NAME", "Super Administrator"), help="Admin display name")
    parser.add_argument("--password", default=None, help="[DEPRECATED] Admin password on CLI is discouraged. Prefer ADMIN_BOOTSTRAP_PASSWORD environment variable or interactive prompt.")
    parser.add_argument("--rotate", action="store_true", help="Rotate password if admin already exists")
    parser.add_argument("--non-interactive", action="store_true", help="Fail if password not supplied via env or arg")

    args = parser.parse_args()

    # Secret handling: prefer environment variable, fallback to CLI arg (with warning) or interactive prompt
    password = os.getenv("ADMIN_BOOTSTRAP_PASSWORD")
    if not password and args.password:
        warnings.warn(
            "Passing passwords via the '--password' CLI argument is deprecated for security reasons; "
            "credentials may be visible in process listings or shell history. "
            "Please use the ADMIN_BOOTSTRAP_PASSWORD environment variable or interactive prompt instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        password = args.password

    if not password:
        if args.non_interactive or not sys.stdin.isatty():
            print("ERROR: Password required via ADMIN_BOOTSTRAP_PASSWORD in non-interactive mode.", file=sys.stderr)
            sys.exit(1)
        password = getpass.getpass("Enter Super Admin password (min 12 characters): ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("ERROR: Passwords do not match.", file=sys.stderr)
            sys.exit(1)

    try:
        bootstrap_admin(
            email=args.email,
            username=args.username,
            password=password,
            display_name=args.display_name,
            rotate=args.rotate,
        )
    except AccountAlreadyExistsError as e:
        print(f"ALREADY_EXISTS: {e}", file=sys.stderr)
        sys.exit(2)
    except BootstrapError as e:
        print(f"BOOTSTRAP_ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
