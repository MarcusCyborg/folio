"""The two supported account roles and their administrative capabilities."""

ROLES_CATALOG = [
    ("member", "Library Member"),
    ("super_admin", "Super Admin"),
]
SUPPORTED_ROLES = frozenset(key for key, _ in ROLES_CATALOG)

PERMISSIONS_CATALOG = [
    ("documents:write", "Create, edit, publish and soft-delete library documents"),
    ("taxonomy:write", "Create, update and delete categories and tags"),
    ("moderation:manage", "Review and moderate comments, handle flags and suspend commenting"),
    ("seo:write", "Update document SEO metadata, keywords and image alt text"),
    ("analytics:read", "Access analytics dashboards, search logs and document views"),
    ("users:manage", "Manage user accounts, assign roles and deactivate users"),
    ("roles:manage", "View the protected role permissions matrix"),
    ("audit:read", "View system and security audit logs"),
    ("settings:write", "Configure site settings and toggles"),
]

ROLE_PERMISSIONS_DEFAULTS = {
    "super_admin": [key for key, _ in PERMISSIONS_CATALOG],
}
