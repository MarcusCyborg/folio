import re
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from src.backend.models.document import Document, DocumentLike
from src.backend.models.comment import Comment, CommentMention, Report
from src.backend.models.auth import User
from src.backend.models.system import AppSetting
from src.backend.core.exceptions import AppException

MENTION_REGEX = re.compile(r"@([a-z0-9_]{3,30})", re.IGNORECASE)

def escape_sql_wildcards(val: str) -> str:
    return val.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

def toggle_like(db: Session, doc_id: str, user_id: str, like_action: bool) -> Tuple[bool, int]:
    doc = db.query(Document).filter(
        Document.id == doc_id,
        Document.status == "published",
        Document.deleted_at.is_(None)
    ).first()
    if not doc:
        raise AppException(status_code=404, code="DOCUMENT_NOT_FOUND", message="Document not found or not published")

    existing_like = db.query(DocumentLike).filter(
        DocumentLike.document_id == doc_id,
        DocumentLike.user_id == user_id
    ).first()

    if like_action:
        if not existing_like:
            try:
                db.add(DocumentLike(document_id=doc_id, user_id=user_id))
                db.commit()
            except IntegrityError:
                db.rollback()
    else:
        if existing_like:
            db.delete(existing_like)
            db.commit()

    likes_count = db.query(DocumentLike).filter(DocumentLike.document_id == doc_id).count()
    return like_action, likes_count

def list_comments(db: Session, doc_id: str, current_user_id: Optional[str] = None, page: int = 1, page_size: int = 20) -> Tuple[List[dict], int]:
    doc = db.query(Document).filter(
        Document.id == doc_id,
        Document.status == "published",
        Document.deleted_at.is_(None)
    ).first()
    if not doc:
        raise AppException(status_code=404, code="DOCUMENT_NOT_FOUND", message="Document not found")

    query = db.query(Comment).filter(
        Comment.document_id == doc_id,
        Comment.status == "visible"
    ).order_by(Comment.created_at.asc(), Comment.id.asc())

    total = query.count()
    comments = query.offset((page - 1) * page_size).limit(page_size).all()

    results = []
    for c in comments:
        mentions_list = [
            {"id": m.mentioned_user.id, "username": m.mentioned_user.username, "display_name": m.mentioned_user.display_name}
            for m in c.mentions if m.mentioned_user
        ]
        results.append({
            "id": c.id,
            "document_id": c.document_id,
            "author": {
                "id": c.author.id,
                "username": c.author.username,
                "display_name": c.author.display_name,
            },
            "body": c.body,
            "mentions": mentions_list,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
            "can_edit": (current_user_id is not None and c.user_id == current_user_id and c.status == "visible"),
            "can_delete": (current_user_id is not None and c.user_id == current_user_id),
        })

    return results, total

def extract_mentions(db: Session, text: str) -> List[User]:
    matches = set(MENTION_REGEX.findall(text))
    if not matches:
        return []
    lowered = [m.lower() for m in matches]
    return db.query(User).filter(
        func.lower(User.username).in_(lowered),
        User.is_active == True
    ).all()

def create_comment(db: Session, doc_id: str, user: User, body: str) -> dict:
    clean_body = body.strip()
    if not clean_body:
        raise AppException(status_code=422, code="EMPTY_COMMENT", message="Comment cannot be empty")

    # 1. Check global comments_enabled
    setting = db.query(AppSetting).filter(AppSetting.key == "comments_enabled").first()
    if setting and setting.value is False:
        raise AppException(status_code=403, code="COMMENTS_DISABLED", message="Commenting is disabled by administrator")

    # 2. Check user commenting suspension
    now_utc = datetime.now(timezone.utc)
    if user.commenting_suspended_until and user.commenting_suspended_until > now_utc:
        raise AppException(
            status_code=403,
            code="COMMENTING_SUSPENDED",
            message=f"Your commenting privileges are suspended until {user.commenting_suspended_until.isoformat()}"
        )

    # 3. Check document publication
    doc = db.query(Document).filter(
        Document.id == doc_id,
        Document.status == "published",
        Document.deleted_at.is_(None)
    ).first()
    if not doc:
        raise AppException(status_code=404, code="DOCUMENT_NOT_FOUND", message="Document not found or not published")

    # 4. Anti-spam checks: duplicate content in past 120s or rate limit > 5 comments in 60s
    recent_cutoff = now_utc - timedelta(seconds=120)
    duplicate = db.query(Comment).filter(
        Comment.user_id == user.id,
        Comment.document_id == doc_id,
        Comment.body == clean_body,
        Comment.created_at >= recent_cutoff
    ).first()
    if duplicate:
        raise AppException(status_code=429, code="DUPLICATE_COMMENT", message="You recently posted an identical comment")

    burst_cutoff = now_utc - timedelta(seconds=60)
    burst_count = db.query(Comment).filter(
        Comment.user_id == user.id,
        Comment.created_at >= burst_cutoff
    ).count()
    if burst_count >= 5:
        raise AppException(status_code=429, code="RATE_LIMITED", message="Please slow down. You are commenting too quickly.")

    # 5. Insert comment & mentions
    comment = Comment(
        document_id=doc_id,
        user_id=user.id,
        body=clean_body,
        status="visible",
    )
    db.add(comment)
    db.flush()

    mentioned_users = extract_mentions(db, clean_body)
    for mu in mentioned_users:
        db.add(CommentMention(comment_id=comment.id, mentioned_user_id=mu.id))
    db.commit()
    db.refresh(comment)

    mentions_list = [
        {"id": mu.id, "username": mu.username, "display_name": mu.display_name}
        for mu in mentioned_users
    ]

    return {
        "id": comment.id,
        "document_id": comment.document_id,
        "author": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
        },
        "body": comment.body,
        "mentions": mentions_list,
        "created_at": comment.created_at,
        "updated_at": comment.updated_at,
        "can_edit": True,
        "can_delete": True,
    }

def update_comment(db: Session, comment_id: str, user: User, body: str) -> dict:
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment or comment.status == "deleted":
        raise AppException(status_code=404, code="COMMENT_NOT_FOUND", message="Comment not found")

    # 1. Check parent document publication
    doc = db.query(Document).filter(
        Document.id == comment.document_id,
        Document.status == "published",
        Document.deleted_at.is_(None)
    ).first()
    if not doc:
        raise AppException(status_code=404, code="DOCUMENT_NOT_FOUND", message="Document not found or not published")

    # 2. Check ownership
    if comment.user_id != user.id:
        raise AppException(status_code=403, code="FORBIDDEN", message="You do not own this comment")

    # 3. Prevent owner from editing moderated comment
    if comment.status in ("hidden", "spam"):
        raise AppException(
            status_code=403,
            code="CANNOT_EDIT_MODERATED_COMMENT",
            message="This comment has been hidden or marked as spam by moderation and cannot be edited"
        )
    if comment.status != "visible":
        raise AppException(status_code=403, code="FORBIDDEN", message="Only visible comments can be edited")

    # 4. Check global comments_enabled
    setting = db.query(AppSetting).filter(AppSetting.key == "comments_enabled").first()
    if setting and setting.value is False:
        raise AppException(status_code=403, code="COMMENTS_DISABLED", message="Commenting is disabled by administrator")

    # 5. Check user commenting suspension
    now_utc = datetime.now(timezone.utc)
    if user.commenting_suspended_until and user.commenting_suspended_until > now_utc:
        raise AppException(
            status_code=403,
            code="COMMENTING_SUSPENDED",
            message=f"Your commenting privileges are suspended until {user.commenting_suspended_until.isoformat()}"
        )

    clean_body = body.strip()
    if not clean_body:
        raise AppException(status_code=422, code="EMPTY_COMMENT", message="Comment cannot be empty")

    comment.body = clean_body
    comment.updated_at = datetime.now(timezone.utc)
    db.flush()

    # Re-derive mentions
    db.query(CommentMention).filter(CommentMention.comment_id == comment.id).delete()
    mentioned_users = extract_mentions(db, clean_body)
    for mu in mentioned_users:
        db.add(CommentMention(comment_id=comment.id, mentioned_user_id=mu.id))

    db.commit()
    db.refresh(comment)

    mentions_list = [
        {"id": mu.id, "username": mu.username, "display_name": mu.display_name}
        for mu in mentioned_users
    ]

    return {
        "id": comment.id,
        "document_id": comment.document_id,
        "author": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
        },
        "body": comment.body,
        "mentions": mentions_list,
        "created_at": comment.created_at,
        "updated_at": comment.updated_at,
        "can_edit": True,
        "can_delete": True,
    }

def delete_comment(db: Session, comment_id: str, user: User):
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment or comment.status == "deleted":
        raise AppException(status_code=404, code="COMMENT_NOT_FOUND", message="Comment not found")

    # Check parent document publication
    doc = db.query(Document).filter(
        Document.id == comment.document_id,
        Document.status == "published",
        Document.deleted_at.is_(None)
    ).first()
    if not doc:
        raise AppException(status_code=404, code="DOCUMENT_NOT_FOUND", message="Document not found or not published")

    if comment.user_id != user.id:
        raise AppException(status_code=403, code="FORBIDDEN", message="You do not own this comment")

    # Owner can delete even if suspended
    comment.status = "deleted"
    comment.updated_at = datetime.now(timezone.utc)
    db.commit()

def search_mentions(db: Session, q: str, page: int = 1, page_size: int = 10) -> List[dict]:
    clean_q = escape_sql_wildcards(q.strip())
    if len(q.strip()) < 2:
        return []
    page_size = min(page_size, 10)
    users = db.query(User).filter(
        User.is_active == True,
        (User.username.ilike(f"%{clean_q}%") | User.display_name.ilike(f"%{clean_q}%"))
    ).order_by(User.username.asc(), User.id.asc()).offset((page - 1) * page_size).limit(page_size).all()

    return [
        {"id": u.id, "username": u.username, "display_name": u.display_name}
        for u in users
    ]

def report_comment(db: Session, comment_id: str, user: User, reason: str, details: Optional[str] = None) -> dict:
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment or comment.status != "visible":
        raise AppException(status_code=404, code="COMMENT_NOT_FOUND", message="Comment not found or not visible")

    # Verify parent document
    doc = db.query(Document).filter(
        Document.id == comment.document_id,
        Document.status == "published",
        Document.deleted_at.is_(None)
    ).first()
    if not doc:
        raise AppException(status_code=404, code="DOCUMENT_NOT_FOUND", message="Parent document is not published")

    # Duplicate check: cannot submit multiple open reports on the same comment
    existing_open = db.query(Report).filter(
        Report.comment_id == comment_id,
        Report.reporter_id == user.id,
        Report.status == "open"
    ).first()
    if existing_open:
        raise AppException(status_code=409, code="DUPLICATE_REPORT", message="You already submitted an open report for this comment")

    report = Report(
        comment_id=comment_id,
        reporter_id=user.id,
        reason=reason,
        details=details.strip() if details else None,
        status="open",
    )
    db.add(report)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppException(status_code=409, code="DUPLICATE_REPORT", message="You already submitted an open report for this comment")
    return {"id": report.id, "status": "open"}
