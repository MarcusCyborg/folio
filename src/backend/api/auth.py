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
from src.backend.core.rate_limit import (
    rate_limiter,
    get_client_ip,
    build_login_target_key,
    build_login_ip_key,
    RateLimitStoreUnavailableError,
)
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
    created_at = user.created_at
    if created_at is None:
        from src.backend.models.base import utcnow
        created_at = utcnow()
    return UserSelf(
        id=user.id,
        email=user.email,
        username=user.username,
        display_name=user.display_name,
        bio=user.bio,
        role_key=user.role_key,
        is_active=user.is_active,
        permissions=effective,
        created_at=created_at,
        commenting_suspended_until=user.commenting_suspended_until,
    )

@router.get("/session", response_model=SessionResponse)
def get_current_session(
    ctx: SessionContext = Depends(get_session_context),
    db: Session = Depends(get_db),
):
    """Returns the current session details (authenticated or guest)."""
    user_self = None
    if ctx.user and ctx.user.is_active:
        user_self = user_to_user_self(ctx.user, db)
    return SessionResponse(
        user=user_self,
        csrf_token=ctx.session.csrf_token,
    )

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
        try:
            reg_res = rate_limiter.check_and_record_register(
                client_ip,
                max_attempts=settings.RATE_LIMIT_REGISTER_MAX,
                window_seconds=settings.RATE_LIMIT_REGISTER_WINDOW_SECONDS,
            )
            if not reg_res:
                raise AppException(
                    status_code=429,
                    code="TOO_MANY_REQUESTS",
                    message="Too many registration attempts. Please wait before trying again.",
                    headers={"Retry-After": str(reg_res.retry_after)},
                )
        except RateLimitStoreUnavailableError as exc:
            raise AppException(
                status_code=503,
                code="RATE_LIMIT_UNAVAILABLE",
                message="Registration rate-limiting service temporarily unavailable. Please try again later.",
            ) from exc

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
    rate_limit_user_key = build_login_target_key(client_ip, normalized_email)
    rate_limit_ip_key = build_login_ip_key(client_ip)

    reservation_token: Optional[str] = None
    reservation_handled = False

    if settings.RATE_LIMIT_ENABLED:
        try:
            admission = rate_limiter.reserve_login_attempt(
                target_identifier=rate_limit_user_key,
                ip_identifier=rate_limit_ip_key,
                max_target_failed=settings.RATE_LIMIT_LOGIN_MAX_FAILED,
                max_ip_failed=settings.RATE_LIMIT_LOGIN_MAX_FAILED * 3,
                window_seconds=settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS,
            )
            if not admission:
                retry_after = max(admission.retry_after, 1)
                raise AppException(
                    status_code=429,
                    code="TOO_MANY_REQUESTS",
                    message="Too many failed login attempts. Please wait before trying again.",
                    headers={"Retry-After": str(retry_after)},
                )
            reservation_token = admission.reservation_token
        except RateLimitStoreUnavailableError as exc:
            raise AppException(
                status_code=503,
                code="RATE_LIMIT_UNAVAILABLE",
                message="Authentication rate-limiting service temporarily unavailable. Please try again later.",
            ) from exc

    try:
        user = db.query(User).filter(func.lower(User.email) == normalized_email).first()

        if not user or not verify_password(data.password, user.password_hash):
            if settings.RATE_LIMIT_ENABLED:
                try:
                    rate_limiter.commit_login_reservation_failure(
                        [rate_limit_user_key, rate_limit_ip_key],
                        reservation_token=reservation_token,
                        window_seconds=settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS,
                    )
                    reservation_handled = True
                except RateLimitStoreUnavailableError as exc:
                    raise AppException(
                        status_code=503,
                        code="RATE_LIMIT_UNAVAILABLE",
                        message="Authentication rate-limiting service temporarily unavailable. Please try again later.",
                    ) from exc
            raise AppException(
                status_code=401,
                code="INVALID_CREDENTIALS",
                message="Invalid email or password",
            )

        if not user.is_active:
            if settings.RATE_LIMIT_ENABLED and reservation_token:
                try:
                    rate_limiter.release_login_reservation(
                        [rate_limit_user_key, rate_limit_ip_key],
                        reservation_token=reservation_token,
                        window_seconds=settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS,
                    )
                    reservation_handled = True
                except RateLimitStoreUnavailableError:
                    pass
            raise AppException(
                status_code=403,
                code="ACCOUNT_DISABLED",
                message="Your account has been deactivated",
            )

        # Successful login: reset failed login attempts for this target account only.
        # Note: rate_limit_ip_key failures are preserved; only the in-flight reservation is released.
        if settings.RATE_LIMIT_ENABLED:
            try:
                rate_limiter.commit_login_reservation_success(
                    target_identifier=rate_limit_user_key,
                    ip_identifier=rate_limit_ip_key,
                    reservation_token=reservation_token,
                    window_seconds=settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS,
                )
                reservation_handled = True
            except RateLimitStoreUnavailableError:
                pass

        new_session, raw_token = rotate_session(db, ctx.session, user=user)
        db.commit()
        set_session_cookie(response, raw_token)

        return SessionResponse(
            user=user_to_user_self(user, db),
            csrf_token=new_session.csrf_token,
        )
    finally:
        if settings.RATE_LIMIT_ENABLED and reservation_token and not reservation_handled:
            try:
                rate_limiter.release_login_reservation(
                    [rate_limit_user_key, rate_limit_ip_key],
                    reservation_token=reservation_token,
                    window_seconds=settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS,
                )
            except Exception:
                pass

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
