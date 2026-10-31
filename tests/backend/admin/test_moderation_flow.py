import pytest
from datetime import datetime, timezone, timedelta
from src.backend.models.comment import Comment, Report
from src.backend.models.document import Document
from src.backend.models.auth import User

def auth_login(client, email, password="FolioDemo2026!"):
    sess = client.get("/api/v1/auth/session").json()
    res = client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": sess["csrf_token"]},
        json={"email": email, "password": password}
    )
    assert res.status_code == 200
    return res.json()["csrf_token"]

def test_moderation_atomic_resolution_and_no_resurrect(client, db_session):
    doc = db_session.query(Document).filter(Document.status == "published").first()
    reader = db_session.query(User).filter(User.username == "reader").first()

    # 1. Create comment and report
    comment1 = Comment(
        document_id=doc.id,
        user_id=reader.id,
        body="Check out this shady cryptocurrency scheme http://spam.xyz",
        status="visible"
    )
    db_session.add(comment1)
    db_session.flush()

    report1 = Report(
        comment_id=comment1.id,
        reporter_id=reader.id,
        reason="spam",
        details="Spam link to crypto site",
        status="open"
    )
    db_session.add(report1)
    db_session.commit()

    csrf_mod = auth_login(client, "moderator@folio.test")

    # Verify report in admin reports list
    reports_res = client.get("/api/v1/admin/reports?status=open").json()
    assert any(r["id"] == report1.id for r in reports_res["items"])

    # 2. Atomic resolution: mark_spam -> report becomes resolved, comment becomes spam in same commit
    res_spam = client.patch(
        f"/api/v1/admin/reports/{report1.id}",
        headers={"X-CSRF-Token": csrf_mod},
        json={"action": "mark_spam", "resolution": "Confirmed spam URL"}
    )
    assert res_spam.status_code == 200
    assert res_spam.json()["status"] == "resolved"

    db_session.refresh(comment1)
    db_session.refresh(report1)
    assert report1.status == "resolved"
    assert comment1.status == "spam"

    # Public comments list for this document must NOT show spam comment
    pub_comments = client.get(f"/api/v1/documents/{doc.id}/comments").json()
    assert all(c["id"] != comment1.id for c in pub_comments["items"])

    # 3. Dismiss action on a report
    comment2 = Comment(document_id=doc.id, user_id=reader.id, body="Legitimate disagreement on methodology", status="visible")
    db_session.add(comment2)
    db_session.flush()
    report2 = Report(comment_id=comment2.id, reporter_id=reader.id, reason="abuse", details="I disagree with this", status="open")
    db_session.add(report2)
    db_session.commit()

    res_dismiss = client.patch(
        f"/api/v1/admin/reports/{report2.id}",
        headers={"X-CSRF-Token": csrf_mod},
        json={"action": "dismiss", "resolution": "No policy violation found"}
    )
    assert res_dismiss.status_code == 200
    assert res_dismiss.json()["status"] == "dismissed"

    db_session.refresh(comment2)
    assert comment2.status == "visible"

    # 4. Invariant: Cannot resurrect owner-deleted comment
    comment_del = Comment(document_id=doc.id, user_id=reader.id, body="Personal comment deleted by owner", status="deleted")
    db_session.add(comment_del)
    db_session.flush()

    # Moderator attempts to resurrect deleted comment -> 400 CANNOT_RESURRECT_DELETED_COMMENT
    res_resurrect = client.patch(
        f"/api/v1/admin/comments/{comment_del.id}/status",
        headers={"X-CSRF-Token": csrf_mod},
        json={"status": "visible"}
    )
    assert res_resurrect.status_code == 400
    assert res_resurrect.json()["error"]["code"] == "CANNOT_RESURRECT_DELETED_COMMENT"

    # 5. Commenting suspension
    suspension_time = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    suspend_res = client.patch(
        f"/api/v1/admin/users/{reader.id}/commenting",
        headers={"X-CSRF-Token": csrf_mod},
        json={"suspended_until": suspension_time, "reason": "Repeated spam links posted"}
    )
    assert suspend_res.status_code == 200
    assert suspend_res.json()["commenting_suspended_until"] is not None

    # Blank reason is rejected
    bad_suspend = client.patch(
        f"/api/v1/admin/users/{reader.id}/commenting",
        headers={"X-CSRF-Token": csrf_mod},
        json={"suspended_until": suspension_time, "reason": "   "}
    )
    assert bad_suspend.status_code == 422

    # Verify suspended user cannot comment on public documents
    csrf_reader = auth_login(client, "reader@folio.test")
    post_comment_res = client.post(
        f"/api/v1/documents/{doc.id}/comments",
        headers={"X-CSRF-Token": csrf_reader},
        json={"body": "Trying to comment while suspended"}
    )
    assert post_comment_res.status_code == 403

    # Remove suspension
    auth_login(client, "moderator@folio.test")
    client.patch(
        f"/api/v1/admin/users/{reader.id}/commenting",
        headers={"X-CSRF-Token": csrf_mod},
        json={"suspended_until": None, "reason": "Suspension lifted"}
    )
