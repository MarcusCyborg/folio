"""Consolidate administration into Super Admin and retain reader accounts.

Revision ID: 20261114_consolidate_roles
Revises: 20261106_report_open_unique
"""
from datetime import datetime, timezone
import uuid

from alembic import op
import sqlalchemy as sa


revision = "20261114_consolidate_roles"
down_revision = "20261106_report_open_unique"
branch_labels = None
depends_on = None

roles = sa.table("roles", sa.column("key", sa.String), sa.column("label", sa.String))
grants = sa.table(
    "role_permissions", sa.column("id", sa.String),
    sa.column("role_key", sa.String), sa.column("permission_key", sa.String),
)
users = sa.table("users", sa.column("id", sa.String), sa.column("role_key", sa.String))
audits = sa.table(
    "audit_logs", sa.column("id", sa.String), sa.column("actor_id", sa.String),
    sa.column("action", sa.String), sa.column("entity_type", sa.String),
    sa.column("entity_id", sa.String), sa.column("before", sa.JSON),
    sa.column("after", sa.JSON), sa.column("timestamp", sa.DateTime(timezone=True)),
)
supported = ("super_admin", "member")


def upgrade():
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(sa.text("SELECT pg_advisory_xact_lock(hashtext('folio_super_admin_protection'))"))

    snapshot = {
        "roles": [dict(row) for row in conn.execute(sa.select(roles).where(roles.c.key.notin_(supported))).mappings()],
        "grants": [dict(row) for row in conn.execute(sa.select(grants).where(grants.c.role_key != "super_admin")).mappings()],
        "users": [dict(row) for row in conn.execute(sa.select(users).where(users.c.role_key.notin_(supported))).mappings()],
    }
    for key, label in (("member", "Library Member"), ("super_admin", "Super Admin")):
        if conn.execute(sa.select(roles.c.key).where(roles.c.key == key)).first() is None:
            conn.execute(roles.insert().values(key=key, label=label))

    # Preserve identities and authorship; former staff become readers, never new admins.
    conn.execute(users.update().where(users.c.role_key.notin_(supported)).values(role_key="member"))
    conn.execute(grants.delete().where(grants.c.role_key != "super_admin"))
    conn.execute(roles.delete().where(roles.c.key.notin_(supported)))
    op.create_check_constraint("ck_roles_supported_key", "roles", "key IN ('super_admin', 'member')")
    conn.execute(audits.insert().values(
        id=str(uuid.uuid4()), actor_id=None, action="migration.consolidate_roles",
        entity_type="roles", entity_id=revision, before=snapshot,
        after={"roles": list(supported), "reassigned_users": len(snapshot["users"])},
        timestamp=datetime.now(timezone.utc),
    ))


def downgrade():
    conn = op.get_bind()
    op.drop_constraint("ck_roles_supported_key", "roles", type_="check")
    snapshot = conn.execute(
        sa.select(audits.c.before)
        .where(audits.c.action == "migration.consolidate_roles", audits.c.entity_id == revision)
        .order_by(audits.c.timestamp.desc()).limit(1)
    ).scalar_one_or_none()
    if not snapshot:
        return
    for role in snapshot["roles"]:
        if conn.execute(sa.select(roles.c.key).where(roles.c.key == role["key"])).first() is None:
            conn.execute(roles.insert().values(**role))
    for grant in snapshot["grants"]:
        exists = conn.execute(sa.select(grants.c.id).where(
            grants.c.role_key == grant["role_key"], grants.c.permission_key == grant["permission_key"],
        )).first()
        if exists is None:
            conn.execute(grants.insert().values(**grant))
    for user in snapshot["users"]:
        # Keep any subsequent promotion to Super Admin intact.
        conn.execute(users.update().where(
            users.c.id == user["id"], users.c.role_key == "member",
        ).values(role_key=user["role_key"]))
