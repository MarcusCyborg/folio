#!/usr/bin/env python3
"""
Folio Initial Admin Provisioning & Rotation CLI.

Safely provisions or rotates the primary super_admin credentials without hardcoding
or logging credentials. Compatible with interactive terminal (hidden password prompt)
and automated container/CI deployment via environment variables.
"""

import sys
import os
import argparse
import getpass
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

def validate_admin_password(password: str, env: str) -> None:
    if len(password) < 12:
        raise ValueError("Admin password must be at least 12 characters long.")
    if env in ("production", "staging"):
        if password.lower() in WEAK_PASSWORDS:
            raise ValueError(f"Admin password is too weak or matches demo defaults for {env}.")
        if len(set(password)) < 6:
            raise ValueError("Admin password has insufficient character diversity/entropy.")

def bootstrap_admin(
    email: str,
    username: str,
    password: str,
    display_name: str = "Super Administrator",
    rotate: bool = False,
    db: Session = None,
) -> User:
    """
    Provisions a new Super Admin or rotates credentials of an existing Super Admin.
    Guarantees no plain text passwords are logged.
    """
    should_close_db = False
    if db is None:
        db = SessionLocal()
        should_close_db = True

    try:
        validate_admin_password(password, settings.APP_ENV)

        # Ensure base taxonomy, roles, and permissions exist
        seed_roles_and_permissions(db)
        seed_settings(db)

        norm_email = email.strip().lower()
        norm_username = username.strip().lower()

        existing_user = db.query(User).filter(
            (func.lower(User.email) == norm_email) | (func.lower(User.username) == norm_username)
        ).first()

        if existing_user:
            if not rotate:
                raise ValueError(
                    f"User '{existing_user.username}' ({existing_user.email}) already exists. "
                    f"Specify --rotate to update password."
                )

            before_state = {
                "role_key": existing_user.role_key,
                "is_active": existing_user.is_active,
            }
            existing_user.password_hash = hash_password(password)
            existing_user.role_key = "super_admin"
            existing_user.is_active = True
            if display_name:
                existing_user.display_name = display_name

            # Revoke all active sessions of this admin on rotation
            revoked_count = revoke_user_sessions(db, existing_user.id)

            write_audit(
                db=db,
                actor=existing_user,
                action="auth.admin_bootstrap_rotated",
                entity_type="user",
                entity_id=existing_user.id,
                before=before_state,
                after={"role_key": "super_admin", "is_active": True, "sessions_revoked": revoked_count},
            )
            db.commit()
            print(f"[SUCCESS] Admin account '{existing_user.username}' ({existing_user.email}) password rotated. Revoked {revoked_count} active sessions.")
            return existing_user

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
        db.commit()
        print(f"[SUCCESS] Initial Super Admin account '{new_admin.username}' ({new_admin.email}) provisioned successfully.")
        return new_admin

    except Exception:
        db.rollback()
        raise
    finally:
        if should_close_db:
            db.close()

def main():
    parser = argparse.ArgumentParser(description="Folio Admin Bootstrap & Rotation CLI")
    parser.add_argument("--email", default=os.getenv("ADMIN_BOOTSTRAP_EMAIL", "admin@folio.local"), help="Admin email address")
    parser.add_argument("--username", default=os.getenv("ADMIN_BOOTSTRAP_USERNAME", "admin"), help="Admin username")
    parser.add_argument("--display-name", default=os.getenv("ADMIN_BOOTSTRAP_DISPLAY_NAME", "Super Administrator"), help="Admin display name")
    parser.add_argument("--password", default=os.getenv("ADMIN_BOOTSTRAP_PASSWORD"), help="Admin password (if omitted, prompted securely)")
    parser.add_argument("--rotate", action="store_true", help="Rotate password if admin already exists")
    parser.add_argument("--non-interactive", action="store_true", help="Fail if password not supplied via env or arg")

    args = parser.parse_args()

    password = args.password
    if not password:
        if args.non_interactive or not sys.stdin.isatty():
            print("ERROR: Password required via ADMIN_BOOTSTRAP_PASSWORD or --password in non-interactive mode.", file=sys.stderr)
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
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
