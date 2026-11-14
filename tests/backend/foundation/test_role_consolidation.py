"""Exercise the data migration on the isolated PostgreSQL test database."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.backend.models.auth import Role, RolePermission, User
from src.backend.models.document import Document
from src.backend.models.system import AuditLog


def test_consolidation_preserves_accounts_authorship_and_can_downgrade(db_session):
    path = Path(__file__).resolve().parents[3] / "alembic/versions/20261114_consolidate_roles.py"
    spec = importlib.util.spec_from_file_location("role_consolidation_migration", path.resolve())
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = db_session.connection()
    migration.op = Operations(MigrationContext.configure(connection))
    migration.op.drop_constraint("ck_roles_supported_key", "roles", type_="check")

    retired = ("content_manager", "moderator", "data_seo")
    admin = db_session.query(User).filter_by(username="admin").one()
    for key in retired:
        db_session.add(Role(key=key, label=key))
    db_session.flush()
    staff = []
    for key in retired:
        user = User(email=f"{key}@old.test", username=key, display_name=key,
                    password_hash=admin.password_hash, role_key=key)
        db_session.add(user)
        db_session.add(RolePermission(role_key=key, permission_key="documents:write"))
        staff.append(user)
    db_session.add(RolePermission(role_key="member", permission_key="users:manage"))
    db_session.flush()
    staff_ids = [user.id for user in staff]
    doc = db_session.query(Document).first()
    doc.created_by = staff_ids[0]
    db_session.flush()
    document_id = doc.id
    original_user_count = db_session.query(User).count()
    original_document_count = db_session.query(Document).count()

    migration.upgrade()
    db_session.expire_all()
    assert {r.key for r in db_session.query(Role)} == {"super_admin", "member"}
    assert db_session.query(User).count() == original_user_count
    assert db_session.query(Document).count() == original_document_count
    assert db_session.get(Document, document_id).created_by == staff_ids[0]
    assert all(db_session.get(User, uid).role_key == "member" for uid in staff_ids)
    assert db_session.get(User, admin.id).role_key == "super_admin"
    assert db_session.query(RolePermission).filter(RolePermission.role_key != "super_admin").count() == 0
    audit = db_session.query(AuditLog).filter_by(action="migration.consolidate_roles").order_by(AuditLog.timestamp.desc()).first()
    assert audit.after["reassigned_users"] == 3
    assert {u["id"] for u in audit.before["users"]} == set(staff_ids)

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(text("INSERT INTO roles (key, label) VALUES ('moderator', 'Moderator')"))

    # A later explicit promotion must survive a rollback of the migration.
    db_session.get(User, staff_ids[2]).role_key = "super_admin"
    db_session.flush()
    migration.downgrade()
    db_session.expire_all()
    assert set(retired).issubset({r.key for r in db_session.query(Role)})
    assert db_session.get(User, staff_ids[0]).role_key == "content_manager"
    assert db_session.get(User, staff_ids[1]).role_key == "moderator"
    assert db_session.get(User, staff_ids[2]).role_key == "super_admin"
    assert db_session.get(Document, document_id).created_by == staff_ids[0]
    assert db_session.query(RolePermission).filter_by(role_key="member", permission_key="users:manage").count() == 1
