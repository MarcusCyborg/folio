import pytest
from src.backend.core.dependencies import get_effective_permissions

def test_roles_and_effective_permissions(db_session):
    from src.backend.models.auth import Role, RolePermission
    from src.backend.core.roles import PERMISSIONS_CATALOG

    assert {r.key for r in db_session.query(Role).all()} == {'super_admin', 'member'}
    for role in ('member', 'content_manager', 'moderator', 'data_seo', 'unknown'):
        assert get_effective_permissions(db_session, role) == set()
    assert get_effective_permissions(db_session, 'super_admin') == {key for key, _ in PERMISSIONS_CATALOG}

    # A stale or manually inserted member grant must never grant admin access.
    db_session.add(RolePermission(role_key='member', permission_key='users:manage'))
    db_session.flush()
    assert get_effective_permissions(db_session, 'member') == set()
