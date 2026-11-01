from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from fastapi import Response
from sqlalchemy.orm import Session
from src.backend.models.auth import SessionModel, User
from src.backend.core.security import (
    generate_session_token,
    hash_session_token,
    generate_csrf_token,
    generate_actor_key,
)
from src.backend.core.config import settings

def create_session(
    db: Session,
    user: Optional[User] = None,
    actor_key: Optional[str] = None,
) -> Tuple[SessionModel, str]:
    """Creates a new session (authenticated or guest)."""
    raw_token = generate_session_token()
    token_hash = hash_session_token(raw_token)
    csrf_token = generate_csrf_token()
    resolved_actor_key = actor_key or generate_actor_key()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.SESSION_MAX_AGE_DAYS)

    session_obj = SessionModel(
        token_hash=token_hash,
        user_id=user.id if user else None,
        actor_key=resolved_actor_key,
        csrf_token=csrf_token,
        expires_at=expires_at,
    )
    db.add(session_obj)
    db.flush()
    return session_obj, raw_token

def get_session_by_token(db: Session, raw_token: str) -> Optional[SessionModel]:
    """Retrieves an active, non-expired session by its raw token."""
    token_hash = hash_session_token(raw_token)
    session_obj = db.query(SessionModel).filter(SessionModel.token_hash == token_hash).first()
    if not session_obj:
        return None
    expires_at = session_obj.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        db.delete(session_obj)
        db.flush()
        return None
    return session_obj

def rotate_session(
    db: Session,
    current_session: Optional[SessionModel],
    user: Optional[User] = None,
) -> Tuple[SessionModel, str]:
    """Rotates session token and CSRF token, preserving the actor_key."""
    actor_key = current_session.actor_key if current_session else None
    if current_session:
        db.delete(current_session)
        db.flush()
    return create_session(db, user=user, actor_key=actor_key)

def revoke_user_sessions(db: Session, user_id: str, except_session_id: Optional[str] = None) -> int:
    """Revokes all sessions belonging to a user except the given session ID."""
    q = db.query(SessionModel).filter(SessionModel.user_id == user_id)
    if except_session_id:
        q = q.filter(SessionModel.id != except_session_id)
    count = q.delete(synchronize_session=False)
    db.flush()
    return count

def set_session_cookie(response: Response, raw_token: str):
    """Sets the HttpOnly session cookie on the response with security flags."""
    max_age = settings.SESSION_MAX_AGE_DAYS * 86400
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=max_age,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,
        path="/",
        secure=settings.COOKIE_SECURE,
    )

def clear_session_cookie(response: Response):
    """Clears the session cookie matching security flags."""
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,
        secure=settings.COOKIE_SECURE,
    )
