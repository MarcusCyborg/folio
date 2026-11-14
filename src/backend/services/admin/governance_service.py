import re
from datetime import datetime, timezone, timedelta, date
from typing import Optional, List, Tuple, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from src.backend.models.auth import User, Role, Permission, RolePermission
from src.backend.models.system import AuditLog, AppSetting
from src.backend.core.audit import write_audit, redact_payload
from src.backend.core.dependencies import get_effective_permissions
from src.backend.core.exceptions import AppException
from src.backend.core.session import revoke_user_sessions
from src.backend.schemas.auth import UserSelf

def admin_list_users(
    db: Session,
    q: Optional[str] = None,
    role_key: Optional[str] = None,
    is_active: Optional[bool] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[UserSelf], int]:
    query = db.query(User)

    if q and q.strip():
        escaped = q.strip().replace('%', '\\%').replace('_', '\\_')
        safe_q = f"%{escaped}%"
        query = query.filter(User.username.ilike(safe_q) | User.email.ilike(safe_q) | User.display_name.ilike(safe_q))

    if role_key:
        query = query.filter(User.role_key == role_key)

    if is_active is not None:
        query = query.filter(User.is_active == is_active)

    total = query.count()
    users = query.order_by(User.created_at.desc(), User.id.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for u in users:
        perms = sorted(list(get_effective_permissions(db, u.role_key)))
        items.append(UserSelf(
            id=u.id,
            email=u.email,
            username=u.username,
            display_name=u.display_name,
            bio=u.bio,
            role_key=u.role_key,
            permissions=perms,
            is_active=u.is_active,
            commenting_suspended_until=u.commenting_suspended_until,
            created_at=u.created_at,
        ))
    return items, total

def admin_update_user(
    db: Session,
    user_id: str,
    role_key: Optional[str],
    is_active: Optional[bool],
    actor: User,
) -> UserSelf:
    # Under concurrency, acquire transaction-level advisory lock on PostgreSQL to serialize super_admin mutations
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext('folio_super_admin_protection'))"))

    target_user = db.query(User).filter(User.id == user_id).with_for_update().first()
    if not target_user:
        raise AppException(status_code=404, code="USER_NOT_FOUND", message="User not found")

    # Invariant: Protect active last super_admin under concurrency using SELECT FOR UPDATE
    if target_user.role_key == "super_admin" and target_user.is_active:
        demoting_role = role_key is not None and role_key != "super_admin"
        deactivating = is_active is not None and is_active is False
        if demoting_role or deactivating:
            active_admins = (
                db.query(User)
                .filter(User.role_key == "super_admin", User.is_active == True)
                .with_for_update()
                .all()
            )
            other_active_admins = [a for a in active_admins if a.id != target_user.id]
            if len(other_active_admins) == 0:
                raise AppException(
                    status_code=400,
                    code="CANNOT_DEMOTE_LAST_ADMIN",
                    message="Cannot deactivate or demote the last remaining active Super Admin."
                )

    before_state = {"role_key": target_user.role_key, "is_active": target_user.is_active}

    if role_key is not None:
        role = db.query(Role).filter(Role.key == role_key).first()
        if not role:
            raise AppException(status_code=422, code="INVALID_ROLE", message=f"Role '{role_key}' does not exist")
        target_user.role_key = role.key

    if is_active is not None:
        target_user.is_active = is_active
        # AUTH-02: Ensure sessions from prior to deactivation do not resuscitate after re-enabling
        if is_active is True and before_state.get("is_active") is False:
            revoke_user_sessions(db, target_user.id)

    target_user.updated_at = datetime.now(timezone.utc)
    write_audit(
        db,
        actor=actor,
        action="user.update",
        entity_type="user",
        entity_id=target_user.id,
        before=before_state,
        after={"role_key": target_user.role_key, "is_active": target_user.is_active}
    )
    db.commit()
    db.refresh(target_user)

    perms = sorted(list(get_effective_permissions(db, target_user.role_key)))
    return UserSelf(
        id=target_user.id,
        email=target_user.email,
        username=target_user.username,
        display_name=target_user.display_name,
        bio=target_user.bio,
        role_key=target_user.role_key,
        permissions=perms,
        is_active=target_user.is_active,
        commenting_suspended_until=target_user.commenting_suspended_until,
        created_at=target_user.created_at,
    )

def admin_list_roles(db: Session) -> List[dict]:
    roles = db.query(Role).order_by(Role.key.asc()).all()
    results = []
    for r in roles:
        perms = sorted(list(get_effective_permissions(db, r.key)))
        results.append({
            "key": r.key,
            "label": r.label,
            "permissions": perms,
            "protected": (r.key == "super_admin"),
        })
    return results

def admin_list_permissions(db: Session) -> List[dict]:
    perms = db.query(Permission).order_by(Permission.key.asc()).all()
    return [{"key": p.key, "description": p.description} for p in perms]

def admin_update_role_permissions(
    db: Session,
    role_key: str,
    permissions_list: List[str],
    actor: User,
) -> dict:
    role = db.query(Role).filter(Role.key == role_key).first()
    if not role:
        raise AppException(status_code=404, code="ROLE_NOT_FOUND", message="Role not found")

    if role.key == "super_admin":
        raise AppException(
            status_code=400,
            code="PROTECTED_ROLE",
            message="Super Admin permissions are system-protected and cannot be modified."
        )

    # Validate catalog
    all_perm_keys = {p[0] for p in db.query(Permission.key).all()}
    invalid = [p for p in permissions_list if p not in all_perm_keys]
    if invalid:
        raise AppException(
            status_code=422,
            code="INVALID_PERMISSIONS",
            message=f"The following permission keys do not exist: {', '.join(invalid)}"
        )

    before_perms = sorted([rp.permission_key for rp in role.role_permissions])

    # Re-assign permissions
    db.query(RolePermission).filter(RolePermission.role_key == role.key).delete()
    for pk in set(permissions_list):
        db.add(RolePermission(role_key=role.key, permission_key=pk))

    write_audit(
        db,
        actor=actor,
        action="role.permissions_update",
        entity_type="role",
        entity_id=role.key,
        before={"permissions": before_perms},
        after={"permissions": sorted(permissions_list)}
    )
    db.commit()

    return {
        "key": role.key,
        "label": role.label,
        "permissions": sorted(permissions_list),
        "protected": False,
    }

def admin_list_audit_logs(
    db: Session,
    actor_id: Optional[str] = None,
    action: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = 1,
    page_size: int = 50,
) -> Tuple[List[dict], int]:
    if date_from and date_to and date_from > date_to:
        raise AppException(
            status_code=422,
            code="INVALID_DATE_RANGE",
            message="date_from must be earlier than or equal to date_to"
        )

    query = db.query(AuditLog)

    if actor_id:
        query = query.filter(AuditLog.actor_id == actor_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if date_from:
        dt_from = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
        query = query.filter(AuditLog.timestamp >= dt_from)
    if date_to:
        try:
            next_day = date_to + timedelta(days=1)
            dt_to = datetime.combine(next_day, datetime.min.time(), tzinfo=timezone.utc)
            query = query.filter(AuditLog.timestamp < dt_to)
        except OverflowError:
            dt_to = datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc)
            query = query.filter(AuditLog.timestamp <= dt_to)

    total = query.count()
    logs = query.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for l in logs:
        items.append({
            "id": l.id,
            "actor_id": l.actor_id,
            "actor_username": l.actor.username if l.actor else None,
            "action": l.action,
            "entity_type": l.entity_type,
            "entity_id": l.entity_id,
            "before": redact_payload(l.before),
            "after": redact_payload(l.after),
            "timestamp": l.timestamp,
        })
    return items, total

def normalize_site_name(raw_name: object) -> object:
    if not isinstance(raw_name, str):
        return raw_name
    name = re.sub(r"\s*—\s*", ": ", raw_name)
    name = re.sub(r"\s*:\s*", ": ", name)
    return re.sub(r"^Folio\s*:", "Folio:", name)

def admin_get_settings(db: Session) -> dict:
    settings = db.query(AppSetting).all()
    setting_map = {s.key: s.value for s in settings}
    raw_site_name = setting_map.get("site_name", "Folio: Knowledge & Research Library")
    site_name = normalize_site_name(raw_site_name)
    return {
        "site_name": site_name,
        "site_description": setting_map.get("site_description", "Curated enterprise document store"),
        "registration_enabled": setting_map.get("registration_enabled", True),
        "comments_enabled": setting_map.get("comments_enabled", True),
    }

def admin_update_settings(db: Session, data: dict, actor: User) -> dict:
    allowed_keys = {"site_name", "site_description", "registration_enabled", "comments_enabled"}
    before_state = admin_get_settings(db)
    after_state = dict(before_state)

    for k, v in data.items():
        if k in allowed_keys and v is not None:
            if k == "site_name":
                if not isinstance(v, str) or not v.strip():
                    raise AppException(status_code=422, code="INVALID_SETTING", message="site_name cannot be empty or blank")
                v = v.strip()
            setting = db.query(AppSetting).filter(AppSetting.key == k).first()
            if not setting:
                setting = AppSetting(key=k, value=v)
                db.add(setting)
            else:
                setting.value = v
            after_state[k] = v

    write_audit(
        db,
        actor=actor,
        action="settings.update",
        entity_type="settings",
        entity_id="global",
        before=before_state,
        after=after_state
    )
    db.commit()
    return after_state
