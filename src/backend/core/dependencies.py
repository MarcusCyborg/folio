from dataclasses import dataclass
from typing import Optional, Callable, Set
from fastapi import Request, Response, Depends
from sqlalchemy.orm import Session

from src.backend.core.config import settings
from src.backend.core.database import get_db
from src.backend.core.security import constant_time_compare
from src.backend.core.session import (
    create_session,
    get_session_by_token,
    set_session_cookie,
    revoke_user_sessions,
)
from src.backend.core.exceptions import AppException
from src.backend.models.auth import SessionModel, User, RolePermission
from src.backend.core.audit import write_audit

@dataclass
class SessionContext:
    session: SessionModel
    actor_key: str
    user: Optional[User]
    csrf_token: str

def get_session_context(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> SessionContext:
    """
    Retrieves or establishes a session context for the request.
    Creates a guest session if none exists.
    Validates CSRF token on unsafe HTTP methods.
    """
    raw_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    session_obj = None

    if raw_token:
        session_obj = get_session_by_token(db, raw_token)

    if not session_obj:
        session_obj, new_raw_token = create_session(db, user=None)
        db.commit()
        set_session_cookie(response, new_raw_token)

    # Validate CSRF for state-modifying HTTP methods
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        client_csrf = request.headers.get("X-CSRF-Token")
        if not client_csrf or not constant_time_compare(client_csrf, session_obj.csrf_token):
            raise AppException(
                status_code=403,
                code="CSRF_FORBIDDEN",
                message="Missing or invalid CSRF token"
            )

    return SessionContext(
        session=session_obj,
        actor_key=session_obj.actor_key,
        user=session_obj.user,
        csrf_token=session_obj.csrf_token,
    )

def get_current_user(
    ctx: SessionContext = Depends(get_session_context),
    db: Session = Depends(get_db),
) -> User:
    """Ensures request is authenticated with an active user account."""
    if not ctx.user:
        raise AppException(
            status_code=401,
            code="UNAUTHORIZED",
            message="Authentication required for this resource"
        )
    
    # Reload fresh user from DB to catch immediate deactivations or role changes
    user = db.query(User).filter(User.id == ctx.user.id).first()
    if not user or not user.is_active:
        if user:
            revoke_user_sessions(db, user.id)
        raise AppException(
            status_code=403,
            code="ACCOUNT_DISABLED",
            message="Your account has been deactivated"
        )
    return user

def get_effective_permissions(db: Session, role_key: str) -> Set[str]:
    """Retrieves current effective permissions for a given role key."""
    if role_key == "super_admin":
        # Super admin has all permissions protected
        from src.backend.models.auth import Permission
        all_perms = db.query(Permission.key).all()
        return {p[0] for p in all_perms}
    
    perms = db.query(RolePermission.permission_key).filter(RolePermission.role_key == role_key).all()
    return {p[0] for p in perms}

def require_permission(permission_key: str) -> Callable:
    """Dependency factory checking that the active user possesses the requested permission."""
    def dependency(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
    ) -> User:
        effective = get_effective_permissions(db, user.role_key)
        if permission_key not in effective:
            raise AppException(
                status_code=403,
                code="FORBIDDEN",
                message=f"Missing required permission: '{permission_key}'"
            )
        return user
    return dependency

def require_any_permission(*permission_keys: str) -> Callable:
    """Dependency factory checking that the active user possesses at least one of the requested permissions."""
    def dependency(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
    ) -> User:
        effective = get_effective_permissions(db, user.role_key)
        if not any(pk in effective for pk in permission_keys):
            raise AppException(
                status_code=403,
                code="FORBIDDEN",
                message="Missing required staff permissions"
            )
        return user
    return dependency
