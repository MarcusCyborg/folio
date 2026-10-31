from typing import Optional
from fastapi import APIRouter, Depends, Response, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.backend.core.config import settings
from src.backend.core.database import get_db
from src.backend.core.dependencies import (
    get_session_context,
    get_current_user,
    get_effective_permissions,
    SessionContext,
)
from src.backend.core.session import (
    rotate_session,
    set_session_cookie,
    revoke_user_sessions,
)
from src.backend.core.security import hash_password, verify_password
from src.backend.core.exceptions import AppException
from src.backend.core.rate_limit import rate_limiter, get_client_ip
from src.backend.models.auth import User
from src.backend.models.system import AppSetting
from src.backend.schemas.auth import (
    UserSelf,
    SessionResponse,
    LoginRequest,
    RegisterRequest,
    UpdateProfileRequest,
    ChangePasswordRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])

def user_to_user_self(user: Optional[User], db: Session) -> Optional[UserSelf]:
    if not user:
        return None
    effective = sorted(list(get_effective_permissions(db, user.role_key)))
    return UserSelf(
        id=user.id,
        email=user.email,
        username=user.username,
        display_name=user.display_name,
        bio=user.bio,
        role_key=user.role_key,
        permissions=effective,
        is_active=user.is_active,
        commenting_suspended_until=user.commenting_suspended_until,
        created_at=user.created_at,
    )

@router.get("/session", response_model=SessionResponse)
def get_session(
    ctx: SessionContext = Depends(get_session_context),
    db: Session = Depends(get_db),
):
    """Returns the current user profile (or null if guest) and CSRF token."""
    user_self = user_to_user_self(ctx.user, db)
    return SessionResponse(user=user_self, csrf_token=ctx.csrf_token)

@router.post("/register", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def register(
    data: RegisterRequest,
    request: Request,
    response: Response,
    ctx: SessionContext = Depends(get_session_context),
    db: Session = Depends(get_db),
):
    """Registers a new user account with role 'member'."""
    client_ip = get_client_ip(request)

    # Check registration rate limit
    if settings.RATE_LIMIT_ENABLED:
        if not rate_limiter.check_and_record_register(
            client_ip,
            max_attempts=settings.RATE_LIMIT_REGISTER_MAX,
            window_seconds=settings.RATE_LIMIT_REGISTER_WINDOW_SECONDS,
        ):
            raise AppException(
                status_code=429,
                code="TOO_MANY_REQUESTS",
                message="Too many registration attempts. Please wait before trying again."
            )

    # Check registration_enabled setting
    setting = db.query(AppSetting).filter(AppSetting.key == "registration_enabled").first()
    if setting and setting.value is False:
        raise AppException(
            status_code=403,
            code="REGISTRATION_DISABLED",
            message="Public user registration is currently disabled by administrator",
        )

    # Check case-insensitive email collision
    normalized_email = data.email.strip().lower()
    existing_email = db.query(User).filter(func.lower(User.email) == normalized_email).first()
    if existing_email:
        raise AppException(
            status_code=409,
            code="EMAIL_EXISTS",
            message="An account with this email address already exists",
            fields={"email": ["Email is already registered"]}
        )

    # Check case-insensitive username collision
    normalized_username = data.username.strip().lower()
    existing_username = db.query(User).filter(func.lower(User.username) == normalized_username).first()
    if existing_username:
        raise AppException(
            status_code=409,
            code="USERNAME_EXISTS",
            message="An account with this username already exists",
            fields={"username": ["Username is already taken"]}
        )

    pwd_hash = hash_password(data.password)
    user = User(
        email=normalized_email,
        username=normalized_username,
        display_name=data.display_name.strip(),
        password_hash=pwd_hash,
        role_key="member",
        is_active=True,
    )
    db.add(user)
    db.flush()

    # Rotate session to the newly created user
    new_session, raw_token = rotate_session(db, ctx.session, user=user)
    db.commit()
    set_session_cookie(response, raw_token)

    return SessionResponse(
        user=user_to_user_self(user, db),
        csrf_token=new_session.csrf_token,
    )

@router.post("/login", response_model=SessionResponse)
def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    ctx: SessionContext = Depends(get_session_context),
    db: Session = Depends(get_db),
):
    """Authenticates with email and password, rotating the session cookie and CSRF token."""
    normalized_email = data.email.strip().lower()
    client_ip = get_client_ip(request)
    rate_limit_user_key = f"{client_ip}:{normalized_email}"
    rate_limit_ip_key = f"{client_ip}:ip"

    if settings.RATE_LIMIT_ENABLED:
        if (
            not rate_limiter.check_login_rate_limit(rate_limit_user_key, settings.RATE_LIMIT_LOGIN_MAX_FAILED, settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS)
            or not rate_limiter.check_login_rate_limit(rate_limit_ip_key, settings.RATE_LIMIT_LOGIN_MAX_FAILED * 3, settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS)
        ):
            raise AppException(
                status_code=429,
                code="TOO_MANY_REQUESTS",
                message="Too many failed login attempts. Please wait before trying again."
            )

    user = db.query(User).filter(func.lower(User.email) == normalized_email).first()

    if not user or not verify_password(data.password, user.password_hash):
        if settings.RATE_LIMIT_ENABLED:
            rate_limiter.record_failed_login(rate_limit_user_key)
            rate_limiter.record_failed_login(rate_limit_ip_key)
        raise AppException(
            status_code=401,
            code="INVALID_CREDENTIALS",
            message="Invalid email or password",
        )

    if not user.is_active:
        raise AppException(
            status_code=403,
            code="ACCOUNT_DISABLED",
            message="Your account has been deactivated",
        )

    # Successful login: reset failed login attempts
    if settings.RATE_LIMIT_ENABLED:
        rate_limiter.record_successful_login(rate_limit_user_key)
        rate_limiter.record_successful_login(rate_limit_ip_key)

    new_session, raw_token = rotate_session(db, ctx.session, user=user)
    db.commit()
    set_session_cookie(response, raw_token)

    return SessionResponse(
        user=user_to_user_self(user, db),
        csrf_token=new_session.csrf_token,
    )

@router.post("/logout", response_model=SessionResponse)
def logout(
    response: Response,
    ctx: SessionContext = Depends(get_session_context),
    db: Session = Depends(get_db),
):
    """Logs out by rotating the session back to a guest session."""
    guest_session, raw_token = rotate_session(db, ctx.session, user=None)
    db.commit()
    set_session_cookie(response, raw_token)
    return SessionResponse(user=None, csrf_token=guest_session.csrf_token)

@router.patch("/profile", response_model=UserSelf)
def update_profile(
    data: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Updates display name or bio of current authenticated user."""
    if data.display_name is not None:
        current_user.display_name = data.display_name.strip()
    if data.bio is not None:
        current_user.bio = data.bio.strip()
    db.commit()
    db.refresh(current_user)
    return user_to_user_self(current_user, db)

@router.post("/password", response_model=SessionResponse)
def change_password(
    data: ChangePasswordRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    ctx: SessionContext = Depends(get_session_context),
    db: Session = Depends(get_db),
):
    """Changes password, revokes other user sessions, and rotates current session."""
    if not verify_password(data.current_password, current_user.password_hash):
        raise AppException(
            status_code=400,
            code="INVALID_PASSWORD",
            message="Current password is incorrect",
            fields={"current_password": ["Incorrect password"]}
        )

    current_user.password_hash = hash_password(data.new_password)
    db.flush()

    # Revoke all other active sessions of this user
    revoke_user_sessions(db, current_user.id, except_session_id=ctx.session.id)

    # Rotate the current session
    new_session, raw_token = rotate_session(db, ctx.session, user=current_user)
    db.commit()
    set_session_cookie(response, raw_token)

    return SessionResponse(
        user=user_to_user_self(current_user, db),
        csrf_token=new_session.csrf_token,
    )
