import pytest
from src.backend.core.dependencies import get_effective_permissions

def test_roles_and_effective_permissions(db_session):
    """Verifies that roles have expected default permissions in database."""
    member_perms = get_effective_permissions(db_session, "member")
    assert len(member_perms) == 0

    cm_perms = get_effective_permissions(db_session, "content_manager")
    assert "documents:write" in cm_perms
    assert "taxonomy:write" in cm_perms
    assert "users:manage" not in cm_perms

    mod_perms = get_effective_permissions(db_session, "moderator")
    assert "moderation:manage" in mod_perms
    assert "documents:write" not in mod_perms

    seo_perms = get_effective_permissions(db_session, "data_seo")
    assert "seo:write" in seo_perms
    assert "analytics:read" in seo_perms
    assert "documents:write" not in seo_perms

    admin_perms = get_effective_permissions(db_session, "super_admin")
    assert len(admin_perms) >= 9
    assert "users:manage" in admin_perms
    assert "roles:manage" in admin_perms
    assert "documents:write" in admin_perms
