import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import func, create_engine

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.core.config import settings
from src.backend.core.database import SessionLocal, engine as default_engine
from src.backend.core.security import hash_password
from src.backend.models.auth import Role, Permission, RolePermission, User
from src.backend.models.taxonomy import Category, Tag
from src.backend.models.document import Document, DocumentTag
from src.backend.models.system import AppSetting, AuditLog

ROLES_CATALOG = [
    ("member", "Library Member"),
    ("content_manager", "Content Manager"),
    ("moderator", "Moderator"),
    ("data_seo", "Data & SEO Specialist"),
    ("super_admin", "Super Admin"),
]

PERMISSIONS_CATALOG = [
    ("documents:write", "Create, edit, publish and soft-delete library documents"),
    ("taxonomy:write", "Create, update and delete categories and tags"),
    ("moderation:manage", "Review and moderate comments, handle flags and suspend commenting"),
    ("seo:write", "Update document SEO metadata, keywords and image alt text"),
    ("analytics:read", "Access analytics dashboards, search logs and document views"),
    ("users:manage", "Manage user accounts, assign roles and deactivate users"),
    ("roles:manage", "Configure role permissions matrix"),
    ("audit:read", "View system and security audit logs"),
    ("settings:write", "Configure site settings and toggles"),
]

ROLE_PERMISSIONS_DEFAULTS = {
    "content_manager": ["documents:write", "taxonomy:write"],
    "moderator": ["moderation:manage"],
    "data_seo": ["seo:write", "analytics:read"],
    "super_admin": [p[0] for p in PERMISSIONS_CATALOG],
}

DEFAULT_SETTINGS = {
    "site_name": "Folio — Knowledge & Research Library",
    "site_description": "Curated enterprise document store and research library",
    "registration_enabled": True,
    "comments_enabled": True,
}

DEMO_USERS = [
    ("admin@folio.test", "admin", "Super Admin", "super_admin", "System administrator and platform maintainer"),
    ("content@folio.test", "content_mgr", "Content Manager", "content_manager", "Lead editor and research taxonomist"),
    ("moderator@folio.test", "moderator", "Community Moderator", "moderator", "Forum curator and discussions moderator"),
    ("seo@folio.test", "seo_specialist", "Data & SEO Specialist", "data_seo", "Analytics coordinator and SEO strategist"),
    ("reader@folio.test", "reader", "Active Reader", "member", "Research scholar and library contributor"),
]

def seed_roles_and_permissions(db: Session):
    for key, label in ROLES_CATALOG:
        if not db.query(Role).filter(Role.key == key).first():
            db.add(Role(key=key, label=label))
    
    for key, desc in PERMISSIONS_CATALOG:
        if not db.query(Permission).filter(Permission.key == key).first():
            db.add(Permission(key=key, description=desc))
    db.flush()

    # Seed default role permissions only if table is empty (preserves admin modifications)
    existing_rp_count = db.query(RolePermission).count()
    if existing_rp_count == 0:
        for role_key, perm_keys in ROLE_PERMISSIONS_DEFAULTS.items():
            for perm_key in perm_keys:
                db.add(RolePermission(role_key=role_key, permission_key=perm_key))
        db.flush()

def seed_settings(db: Session):
    for k, v in DEFAULT_SETTINGS.items():
        if not db.query(AppSetting).filter(AppSetting.key == k).first():
            db.add(AppSetting(key=k, value=v))
    db.flush()

def seed_demo_users(db: Session, skip: bool = False):
    if skip or settings.APP_ENV in ("production", "staging"):
        print(f"Skipping local demo accounts seeding in {settings.APP_ENV} environment.")
        return

    password = settings.DEMO_PASSWORD
    hashed_pwd = hash_password(password)

    for email, username, display_name, role_key, bio in DEMO_USERS:
        existing = db.query(User).filter(
            (func.lower(User.email) == email.lower()) | (func.lower(User.username) == username.lower())
        ).first()
        if not existing:
            user = User(
                email=email,
                username=username,
                display_name=display_name,
                password_hash=hashed_pwd,
                role_key=role_key,
                bio=bio,
                is_active=True,
            )
            db.add(user)
    db.flush()

def seed_taxonomy_and_documents(db: Session):
    fixtures_path = PROJECT_ROOT / "fixtures" / "folio" / "documents.jsonl"
    if not fixtures_path.exists():
        print(f"Warning: Fixture file {fixtures_path} not found. Skipping document seeding.")
        return

    # Cache existing categories and tags
    categories_by_slug = {c.slug: c for c in db.query(Category).all()}
    tags_by_slug = {t.slug: t for t in db.query(Tag).all()}

    # Super admin user for created_by attribution if available
    admin_user = db.query(User).filter(User.username == "admin").first()
    admin_id = admin_user.id if admin_user else None

    with open(fixtures_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)

            cat_slug = item.get("category_slug")
            cat_name = item.get("category_name", cat_slug.replace("-", " ").title())
            if cat_slug not in categories_by_slug:
                new_cat = Category(name=cat_name, slug=cat_slug, description=f"Curated research in {cat_name}")
                db.add(new_cat)
                db.flush()
                categories_by_slug[cat_slug] = new_cat
            category = categories_by_slug[cat_slug]

            # Tags
            doc_tag_objs = []
            for t_slug in item.get("tags", []):
                t_slug = t_slug.strip().lower()
                if not t_slug:
                    continue
                if t_slug not in tags_by_slug:
                    new_tag = Tag(name=t_slug.replace("-", " ").title(), slug=t_slug)
                    db.add(new_tag)
                    db.flush()
                    tags_by_slug[t_slug] = new_tag
                doc_tag_objs.append(tags_by_slug[t_slug])

            doc_id = item.get("id")
            source_url = item.get("source_url")
            existing_doc = db.query(Document).filter(
                (Document.id == doc_id) | (Document.source_url == source_url)
            ).first()

            if not existing_doc:
                created_at = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
                published_at = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00")) if item.get("published_at") else None
                
                doc = Document(
                    id=doc_id,
                    title=item["title"],
                    summary=item["summary"],
                    content=item["content"],
                    category_id=category.id,
                    author=item.get("author", "Wikipedia contributors"),
                    created_by=admin_id,
                    created_at=created_at,
                    published_at=published_at,
                    status=item.get("status", "published"),
                    source_url=source_url,
                    source_license=item.get("source_license", "CC BY-SA 4.0"),
                    source_attribution=item.get("source_attribution", "Wikipedia contributors"),
                    cover_image_url=item.get("cover_image_url"),
                    cover_image_alt=item.get("cover_image_alt"),
                    seo_title=item.get("seo_title"),
                    seo_description=item.get("seo_description"),
                    seo_keywords=item.get("seo_keywords"),
                )
                db.add(doc)
                db.flush()

                for tag_obj in doc_tag_objs:
                    db.add(DocumentTag(document_id=doc.id, tag_id=tag_obj.id))

    db.flush()

def seed_database_all(db: Session, skip_demo_users: bool = False, auto_commit: bool = False):
    """Executes all seed stages within a session.

    If auto_commit is False (default when caller provides Session),
    flushes changes but leaves transaction commit/rollback to caller.
    """
    print("Seeding roles and permissions...")
    seed_roles_and_permissions(db)
    print("Seeding settings...")
    seed_settings(db)
    print("Seeding local demo users...")
    seed_demo_users(db, skip=skip_demo_users)
    print("Seeding taxonomy and documents...")
    seed_taxonomy_and_documents(db)

    # Add audit log for system seeding
    admin_user = db.query(User).filter(User.username == "admin").first()
    db.add(AuditLog(
        actor_id=admin_user.id if admin_user else None,
        action="system.seed",
        entity_type="system",
        entity_id="init",
        after={"timestamp": datetime.now(timezone.utc).isoformat()}
    ))
    if auto_commit:
        db.commit()
    else:
        db.flush()

def run_seed(target=None, db_url=None, skip_demo_users: bool = False):
    """
    Idempotent seeding entry point.
    target can be:
      - None (uses settings.DATABASE_URL via default SessionLocal)
      - a Session instance (caller manages lifecycle and transaction ownership; run_seed will not commit)
      - an Engine instance (run_seed creates an isolated session, commits on success, rollbacks on error)
    db_url can be a database URL string (run_seed creates an engine and session, commits on success).
    skip_demo_users: bool (if True, demo users are skipped; in production/staging they are always skipped).
    """
    if isinstance(target, Session):
        seed_database_all(target, skip_demo_users=skip_demo_users, auto_commit=False)
        return

    owned_engine = None
    if target is not None and hasattr(target, "connect"):
        session_factory = sessionmaker(autocommit=False, autoflush=False, bind=target)
    elif db_url:
        owned_engine = create_engine(db_url, pool_pre_ping=True)
        session_factory = sessionmaker(autocommit=False, autoflush=False, bind=owned_engine)
    else:
        session_factory = SessionLocal

    db = session_factory()
    try:
        seed_database_all(db, skip_demo_users=skip_demo_users, auto_commit=True)
        
        # Report totals
        user_count = db.query(User).count()
        doc_count = db.query(Document).filter(Document.status == "published").count()
        draft_count = db.query(Document).filter(Document.status == "draft").count()
        cat_count = db.query(Category).count()
        tag_count = db.query(Tag).count()
        print(f"Seed complete. Database now contains: {user_count} users, {doc_count} published documents, {draft_count} drafts, {cat_count} categories, {tag_count} tags.")
    except Exception as e:
        db.rollback()
        print(f"Error during seeding: {e}")
        raise
    finally:
        db.close()
        if owned_engine:
            owned_engine.dispose()

def main():
    parser = argparse.ArgumentParser(description="Folio Dataset & Taxonomy Seeding CLI")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--db-url", type=str, default=None, help="Explicit database URL to seed")
    group.add_argument("--test", action="store_true", help="Seed TEST_DATABASE_URL instead of primary DATABASE_URL")
    parser.add_argument("--no-demo-users", action="store_true", help="Skip demo user account creation")
    args = parser.parse_args()

    target_url = args.db_url
    if args.test:
        target_url = settings.TEST_DATABASE_URL

    run_seed(db_url=target_url, skip_demo_users=args.no_demo_users)

if __name__ == "__main__":
    main()
