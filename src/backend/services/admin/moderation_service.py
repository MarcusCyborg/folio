from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from src.backend.models.comment import Comment, Report
from src.backend.models.auth import User
from src.backend.core.audit import write_audit
from src.backend.core.exceptions import AppException

def admin_list_comments(
    db: Session,
    status_filter: Optional[str] = None,
    q: Optional[str] = None,
    document_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> Tuple[List[dict], int]:
    query = db.query(Comment)

    if status_filter:
        query = query.filter(Comment.status == status_filter)
    if document_id:
        query = query.filter(Comment.document_id == document_id)
    if q and q.strip():
        escaped = q.strip().replace('%', '\\%').replace('_', '\\_')
        safe_q = f"%{escaped}%"
        query = query.filter(Comment.body.ilike(safe_q))

    total = query.count()
    comments = query.order_by(Comment.created_at.desc(), Comment.id.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for c in comments:
        items.append({
            "id": c.id,
            "document_id": c.document_id,
            "document_title": c.document.title if c.document else "Unknown Document",
            "author": {
                "id": c.author.id,
                "username": c.author.username,
                "display_name": c.author.display_name,
            },
            "body": c.body,
            "status": c.status,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        })
    return items, total

def admin_update_comment_status(
    db: Session,
    comment_id: str,
    new_status: str,
    reason: Optional[str],
    actor: User,
) -> dict:
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise AppException(status_code=404, code="COMMENT_NOT_FOUND", message="Comment not found")

    if comment.status == "deleted":
        raise AppException(
            status_code=400,
            code="CANNOT_RESURRECT_DELETED_COMMENT",
            message="Cannot alter moderation status of a comment deleted by its owner."
        )

    before_status = comment.status
    comment.status = new_status
    comment.updated_at = datetime.now(timezone.utc)

    write_audit(
        db,
        actor=actor,
        action="moderation.comment_status",
        entity_type="comment",
        entity_id=comment.id,
        before={"status": before_status},
        after={"status": comment.status, "reason": reason}
    )
    db.commit()

    return {
        "id": comment.id,
        "status": comment.status,
        "updated_at": comment.updated_at,
    }

def admin_list_reports(
    db: Session,
    status_filter: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> Tuple[List[dict], int]:
    query = db.query(Report)

    if status_filter:
        query = query.filter(Report.status == status_filter)

    total = query.count()
    reports = query.order_by(Report.created_at.desc(), Report.id.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for r in reports:
        items.append({
            "id": r.id,
            "comment_id": r.comment_id,
            "comment_body": r.comment.body if r.comment else "[Deleted]",
            "comment_status": r.comment.status if r.comment else "unknown",
            "comment_author": {
                "id": r.comment.author.id,
                "username": r.comment.author.username,
                "display_name": r.comment.author.display_name,
            } if r.comment and r.comment.author else None,
            "reporter": {
                "id": r.reporter.id,
                "username": r.reporter.username,
                "display_name": r.reporter.display_name,
            } if r.reporter else None,
            "reason": r.reason,
            "details": r.details,
            "status": r.status,
            "resolution": r.resolution,
            "created_at": r.created_at,
            "handled_at": r.handled_at,
            "handled_by": r.handler.username if r.handler else None,
        })
    return items, total

def admin_resolve_report(
    db: Session,
    report_id: str,
    action: str,
    resolution: Optional[str],
    actor: User,
) -> dict:
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise AppException(status_code=404, code="REPORT_NOT_FOUND", message="Report not found")

    comment = report.comment
    now_utc = datetime.now(timezone.utc)

    before_report_status = report.status
    before_comment_status = comment.status if comment else None

    if action == "dismiss":
        report.status = "dismissed"
    elif action == "hide_comment":
        report.status = "resolved"
        if comment and comment.status != "deleted":
            comment.status = "hidden"
            comment.updated_at = now_utc
    elif action == "mark_spam":
        report.status = "resolved"
        if comment and comment.status != "deleted":
            comment.status = "spam"
            comment.updated_at = now_utc
    else:
        raise AppException(status_code=422, code="INVALID_ACTION", message="Action must be dismiss, hide_comment, or mark_spam")

    report.resolution = resolution
    report.handled_by = actor.id
    report.handled_at = now_utc

    write_audit(
        db,
        actor=actor,
        action=f"moderation.report_{action}",
        entity_type="report",
        entity_id=report.id,
        before={"report_status": before_report_status, "comment_status": before_comment_status},
        after={"report_status": report.status, "action": action, "resolution": resolution}
    )
    db.commit()

    return {
        "id": report.id,
        "status": report.status,
        "action": action,
        "handled_at": report.handled_at,
    }

def admin_suspend_commenting(
    db: Session,
    user_id: str,
    suspended_until: Optional[datetime],
    reason: str,
    actor: User,
) -> dict:
    if not reason or not reason.strip():
        raise AppException(status_code=422, code="INVALID_REASON", message="Reason cannot be empty or whitespace only")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise AppException(status_code=404, code="USER_NOT_FOUND", message="User not found")

    before_until = user.commenting_suspended_until
    user.commenting_suspended_until = suspended_until
    user.updated_at = datetime.now(timezone.utc)

    write_audit(
        db,
        actor=actor,
        action="moderation.suspend_commenting",
        entity_type="user",
        entity_id=user.id,
        before={"commenting_suspended_until": before_until.isoformat() if before_until else None},
        after={"commenting_suspended_until": suspended_until.isoformat() if suspended_until else None, "reason": reason.strip()}
    )
    db.commit()

    return {
        "id": user.id,
        "commenting_suspended_until": user.commenting_suspended_until,
    }
